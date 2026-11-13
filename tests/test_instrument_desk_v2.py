"""The instrument page and its chart, as the desk v2 board draws them (B10,
UI plan S4, 2026-11-13).

The operator approved the desk v2 ("amazing work, bravo, I need it
fast!!"): the instrument board (scratchpad canvas_v2/project/
Instrument2.dc.html) is what this page now is, in the platform's tokens:

  * THE HEADER is one 52 px row: the day's change and range, his REAL
    position on the symbol with its P&L, R and entry, the quote's own words
    and age (the one price's), the market's next change, then the two
    sides, each price on the button that trades at it (the deal ticket,
    its words, form and PIN path untouched).
  * THE CHART takes the height of the screen (at least 60 % of it, at least
    480 px), with ONE toolbar row: the interval favourites, More, Range,
    Candles, Indicators, Levels and Draw as menus that hold every control
    the two old rows held, the size keys, Log, Fit and Full screen.
  * IN THE PANE the legend (O H L C, the change, the bar's time, the frame,
    the candles' feed, the volume and the next bar) stays put at the top
    left; rising candles are hollow and falling ones solid in the data red
    (--sv-down-fill, never REAL's); the volume pane under them at 35 %.
  * THE LEVELS: his stop, target and entry solid, the signal's dashed, the
    one price's line labelled with its words and age; the axis labels on
    the bg-2 surface in their tone (no solid red box that is not REAL);
    the entry wears the world chip (REAL solid red); a level off the view
    is pinned to the pane's edge with an arrow and its distance; no chip
    sits on another.
  * THE KEY at the chart card's foot, one row, "Charts by TradingView" at
    its right end.
  * NO OLD MARKER on the page and the signal rail beside it: every colour a
    token or the kit's mix of one, no text under 11 px, text at 4.5:1 on its
    ground, no glow but the magic's, REAL the only solid red fill.

The money controls keep their words, forms and focus order (plan §10): the
ticket's sides, the rail cards' TAKE TRADE / ADD and PASS, the watchlist
form. The live hooks keep their counts (tests/test_live_hooks_inventory).

Measured in a headless Chromium on the page the test client renders over a
synthetic book (tests/chart_desk_fixture.py), its scripts stripped but the
chart's and the one price's, the chart's reply answered from the test
client's own, the chart library from its pinned copy (tests/vendor), every
network URL blocked. Skipped without Chromium. Display only: no order, no
broker, no model, no network.

Run with:  python manage.py test tests.test_instrument_desk_v2
"""
import base64
import hashlib
import io
import json
import pathlib
import re
import shutil
import tempfile
import time
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests import chart_desk_fixture as F
from tests.test_close_advice import CHROME, _Chrome

ROOT = pathlib.Path(settings.BASE_DIR)
LIB = ROOT / "tests/vendor/lightweight-charts-4.1.0/lightweight-charts.standalone.production.js"
WIDGET = "templates/_partials/chart_widget.html"
PAGE = "templates/dashboard/instrument_detail.html"
SHEET = "static/css/sv-chart.css"
TOKENS = "static/css/sv-tokens.css"
CDN = "https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"
ID = F.CHART_ID

#: The board's data colours (sv-tokens.css): rising candles' edge, falling
#: candles' body, the Eye, the old gold and the old red they replaced.
UP_FILL, DOWN_FILL, REAL = (31, 163, 116), (229, 72, 77), (204, 58, 64)
EYE, OLD_GOLD, OLD_GOLD2, OLD_RED = (0, 232, 104), (216, 176, 32), (208, 176, 32), (232, 48, 48)

#: The money controls of the page, in focus order, as main 1b94a50 has them
#: (the order of the money controls; plan §10 never changes it).
MONEY_ORDER = [
    ("tk-short", "Short XAUUSD at the bid"), ("tk-long", "Long XAUUSD at the ask"),
    ("tk-short", "Short XAUUSD at the bid"), ("tk-long", "Long XAUUSD at the ask"),
]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def token_rgb():
    """{name: [r, g, b]} of every --sv-* colour sv-tokens.css's :root sets
    as a hex (the dark theme)."""
    css = read(TOKENS)
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    out = {}
    for name, hexv in re.findall(r"--sv-([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b", root):
        h = hexv[1:]
        out[name] = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return out


# ══════════════════════════════════════════════════════════════════════════
# The sources
# ══════════════════════════════════════════════════════════════════════════

class TheSourcesTests(SimpleTestCase):
    """The look lives in one sheet on the tokens; the widget and the page
    carry no look of their own; the library is pinned by its hash."""

    def test_the_chart_sheet_exists_and_names_only_tokens(self):
        css = re.sub(r"/\*.*?\*/", "", read(SHEET), flags=re.S)
        # every colour is a token: no hex, rgb() or named colour of its own
        bare = re.sub(r"var\(--[a-z0-9-]+(?:,[^()]*(?:\([^()]*\))?[^()]*)?\)", "", css)
        self.assertNotRegex(bare, r"#[0-9A-Fa-f]{3,8}\b")
        self.assertNotRegex(bare, r"\brgba?\(")
        # nothing under 11 px
        for size in re.findall(r"font-size:\s*([\d.]+)px", css):
            self.assertGreaterEqual(float(size), 11, size)
        self.assertNotIn("backdrop-filter", css)

    def test_the_widget_and_the_page_carry_no_look_of_their_own(self):
        for rel in (WIDGET, PAGE):
            with self.subTest(file=rel):
                src = read(rel)
                self.assertNotIn("<style", src)
                for m in re.finditer(r'\sstyle="([^"]*)"', src):
                    self.assertNotRegex(m.group(1), r"(?<![-\w])(color|background|border|font|box-shadow|text-shadow|filter)\s*:",
                                        m.group(0))
        self.assertIn("css/sv-chart.css", read(WIDGET))

    def test_the_library_is_loaded_with_its_hash_and_the_test_copy_is_that_file(self):
        src = read(WIDGET)
        self.assertIn(CDN, src)
        m = re.search(r"integrity\s*=\s*'(sha384-[A-Za-z0-9+/=]+)'", src)
        self.assertTrue(m, "the loader names the file's hash")
        digest = "sha384-" + base64.b64encode(hashlib.sha384(LIB.read_bytes()).digest()).decode()
        self.assertEqual(m.group(1), digest)
        self.assertIn("crossOrigin = 'anonymous'", src)

    def test_the_toolbar_holds_every_control_the_two_rows_held(self):
        src = read(WIDGET)
        for tf in ("1min", "5min", "10min", "15min", "30min", "1h", "2h", "4h", "1d", "1wk",
                   "1w", "1mo", "3m", "1y"):
            self.assertIn('data-tf="%s"' % tf, src)
        for t in ("candlestick", "heikin", "line", "area"):
            self.assertIn('data-type="%s"' % t, src)
        for ind in ("sma20", "sma50", "ema20", "bb", "vwap", "rsi", "macd", "volume", "positions", "levels"):
            self.assertIn('data-ind="%s"' % ind, src)
        for ctl in ("log", "fit", "tall", "fullscreen"):
            self.assertIn('data-ctl="%s"' % ctl, src)
        for tool in ("crosshair", "hline", "trendline", "measure", "clear"):
            self.assertIn('data-tool="%s"' % tool, src)
        for name in ("More", "Range", "Candles", "Indicators", "Levels", "Draw"):
            self.assertRegex(src, r'aria-haspopup="menu"[^>]*>(<svg[^>]*>.*?</svg>)?(<span data-tb-label>)?%s' % name)

    def test_the_one_price_hands_and_the_chart_hooks_stay(self):
        src = read(WIDGET)
        for key in ("symbol:", "series:", "bars:", "source:", "caption:", "setNow:", "refresh:", "tick:"):
            self.assertIn(key, src[src.index("window.svCharts[CHART_ID] = {"):])
        for suffix in ("-container", "-legend", "-countdown", "-measure", "-panes", "-sig-card",
                       "-sig-legend", "-lvl-legend", "-pos-legend", "-src", "-loading", "-error"):
            self.assertIn('id="{{ chart_id }}%s"' % suffix, src)
        for role in ("feed", "notes", "positions", "tick", "now"):
            self.assertIn('data-role="%s"' % role, src)
        self.assertIn("function tickRefusal(", src)


# ══════════════════════════════════════════════════════════════════════════
# Measured
# ══════════════════════════════════════════════════════════════════════════

PROBE = r"""(function () {
  var ID = '__ID__';
  function box(el) { if (!el) return null; var r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }
  function vis(el) { if (!el || !el.isConnected) return false; var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !el.closest('[hidden]'); }
  function q(s) { return document.querySelector(s); }
  function qa(s, root) { return Array.prototype.slice.call((root || document).querySelectorAll(s)); }
  var R = { vw: innerWidth, vh: innerHeight };
  var ih = q('.sv-ih');
  R.ih = box(ih); R.ihText = ih ? ih.innerText.replace(/\s+/g, ' ') : '';
  R.ihRows = qa('.sv-ih [data-ih-row]').filter(vis).map(function (e) {
    return { h: e.getBoundingClientRect().height, sw: e.scrollWidth, cw: e.clientWidth, t: e.innerText }; });
  R.ihFit = ih ? { sw: ih.scrollWidth, cw: ih.clientWidth } : null;
  R.ihCut = qa('.sv-ih [data-ih-row] *').filter(vis).filter(function (e) {
    return e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline'; })
    .map(function (e) { return String(e.className) + ': ' + e.innerText; });
  R.ihKids = qa('.sv-ih > *').filter(vis).map(function (e) { var o = box(e); o.c = String(e.className); return o; });
  R.ihReal = (function () { var e = ih && ih.querySelector('.sv-world--live');
    return e ? { bg: getComputedStyle(e).backgroundColor, t: e.innerText } : null; })();
  R.ticket = qa('.sv-ih .tk-side').map(function (b) { var o = box(b); o.t = b.innerText.replace(/\s+/g, ' '); return o; });
  var card = q('.sv-chart-card');
  R.card = box(card);
  R.container = box(document.getElementById(ID + '-container'));
  R.body = box(document.getElementById(ID));
  var bottomChrome = null;
  qa('.info-panel-wrap, .sv-statusbar, .ip-strip').forEach(function (e) {
    if (vis(e) && getComputedStyle(e).position === 'fixed') { var r = e.getBoundingClientRect();
      if (r.top > innerHeight / 2) bottomChrome = bottomChrome === null ? r.top : Math.min(bottomChrome, r.top); } });
  R.bottomChrome = bottomChrome;
  var tb = q('#' + ID + '-container .sv-chart-toolbar');
  R.toolbar = box(tb);
  var tops = {};
  R.tools = [];
  if (tb) qa('button, [data-tb-keys]', tb).forEach(function (b) {
    if (!vis(b) || b.closest('[role="menu"]')) return;
    tops[Math.round(b.getBoundingClientRect().top)] = 1;
    R.tools.push({ t: b.innerText.replace(/\s+/g, ' ').trim(), label: b.getAttribute('aria-label') || '',
                   menu: b.getAttribute('aria-haspopup') || '', tf: b.getAttribute('data-tf') || '',
                   ctl: b.getAttribute('data-ctl') || '', pressed: b.getAttribute('aria-pressed') || '' });
  });
  R.toolRows = Object.keys(tops).length;
  R.menus = qa('#' + ID + '-container [role="menu"]').map(function (m) {
    function attrs(a) { return qa('[' + a + ']', m).map(function (e) { return e.getAttribute(a); }); }
    return { id: m.id, shown: vis(m), tf: attrs('data-tf'), type: attrs('data-type'), ind: attrs('data-ind'),
             tool: attrs('data-tool'), ctl: attrs('data-ctl'), lvl: attrs('data-lvl') };
  });
  var lg = document.getElementById(ID + '-legend');
  R.legend = vis(lg) ? box(lg) : null; R.legendText = lg ? lg.innerText.replace(/\s+/g, ' ') : '';
  R.legendRows = lg ? qa('[data-lg-row]', lg).filter(vis).map(function (e) { return box(e); }) : [];
  var key = card ? card.querySelector('.sv-chart-keyrow') : null;
  R.key = vis(key) ? box(key) : null;
  R.keyText = key ? key.innerText.replace(/\s+/g, ' ') : '';
  R.keyKids = key ? qa(':scope > *', key).filter(vis).map(function (e) { return box(e); }) : [];
  var credit = card ? card.querySelector('a[href="https://www.tradingview.com/"]') : null;
  R.credit = vis(credit) ? box(credit) : null;
  R.creditText = credit ? credit.innerText : '';
  var line = credit ? credit.closest('.sv-chart-credit') : null;
  R.creditLine = vis(line) ? box(line) : null;
  R.creditWords = line ? line.innerText.replace(/\s+/g, ' ') : '';
  R.chips = qa('.sv-mchip').filter(vis).map(function (c) {
    var o = box(c); o.t = c.innerText.replace(/\s+/g, ' '); o.cls = c.className; o.edge = c.getAttribute('data-edge') || '';
    return o; });
  R.world = (function () { var e = q('.sv-mchip .sv-world--live');
    return vis(e) ? { bg: getComputedStyle(e).backgroundColor, b: box(e), t: e.innerText } : null; })();
  var h = window.svCharts && svCharts[ID];
  R.bars = h && h.bars ? h.bars().length : 0;
  var s = h && h.series ? h.series() : null;
  R.opts = s && s.options ? (function (o) { return { up: o.upColor, down: o.downColor, bUp: o.borderUpColor,
    bDown: o.borderDownColor, wUp: o.wickUpColor, wDown: o.wickDownColor, last: o.lastValueVisible }; })(s.options()) : null;
  R.y = s ? { entry: s.priceToCoordinate(2658.40), stop: s.priceToCoordinate(2682.00),
              target: s.priceToCoordinate(2610.00), bid: s.priceToCoordinate(2647.72),
              sigEntry: s.priceToCoordinate(2651.40), sigStop: s.priceToCoordinate(2675.40),
              sigTarget: s.priceToCoordinate(2603.40) } : null;
  R.caption = (function () { var c = h && h.caption && h.caption(); return c ? { t: c.textContent, hidden: c.hidden } : null; })();
  R.money = qa('.page-content .tk-side, #railSignalsBody .sr-pop-btn-act, #railSignalsBody .sr-pop-btn-pass, .page-content [data-sv-close-trade]').map(function (b) {
    var k = /tk-short|tk-long|sr-pop-btn-act|sr-pop-btn-pass/.exec(b.className);
    return [k ? k[0] : 'close', b.getAttribute('aria-label') || b.innerText.replace(/\s+/g, ' ').trim()]; });
  R.forms = qa('form').map(function (f) {
    return [f.getAttribute('action'), (f.getAttribute('method') || '').toLowerCase(),
            qa('input, select, textarea, button', f).map(function (e) { return (e.name || '') + ':' + (e.type || e.tagName.toLowerCase()); })]; });
  return JSON.stringify(R);
})()"""

#: The census of the page's own regions: the content and the rail's signals.
CENSUS = r"""(function (TOK, REGIONS) {
  var NEUTRAL = Object.keys(TOK).filter(function (n) { return /^(bg|line|ink)-\d$/.test(n); });
  var ACCENT = Object.keys(TOK).filter(function (n) { return NEUTRAL.indexOf(n) < 0; });
  TOK.white = [255, 255, 255]; ACCENT.push('white');
  function parse(s) {
    if (!s) return null; s = s.trim();
    if (s === 'transparent') return [0, 0, 0, 0];
    var m = /^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(s);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : (/%$/.test(m[4]) ? parseFloat(m[4]) / 100 : +m[4])];
    m = /^color\(srgb\s+([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/.exec(s);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : (/%$/.test(m[4]) ? parseFloat(m[4]) / 100 : +m[4])];
    return null;
  }
  function dist(a, b) { return Math.sqrt(Math.pow(a[0] - b[0], 2) + Math.pow(a[1] - b[1], 2) + Math.pow(a[2] - b[2], 2)); }
  function tokenish(c) {
    var n; for (n in TOK) if (dist(c, TOK[n]) <= 3) return true;
    var i, j, ok = false;
    function pair(A, B, maxT) {
      var a = TOK[A], b = TOK[B], ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], L = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
      if (!L) return;
      var t = ((c[0] - a[0]) * ab[0] + (c[1] - a[1]) * ab[1] + (c[2] - a[2]) * ab[2]) / L;
      if (t < 0 || t > maxT) return;
      if (dist(c, [a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2]]) <= 2.6) ok = true;
    }
    for (i = 0; i < NEUTRAL.length && !ok; i++) for (j = i + 1; j < NEUTRAL.length && !ok; j++) pair(NEUTRAL[i], NEUTRAL[j], 1);
    for (i = 0; i < NEUTRAL.length && !ok; i++) for (j = 0; j < ACCENT.length && !ok; j++) pair(NEUTRAL[i], ACCENT[j], 0.36);
    return ok;
  }
  function lum(c) { var f = function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); }
  function over(top, bot) { var a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; }
  function ground(el) {
    var stack = [], e = el;
    while (e && e.nodeType === 1) { var b = parse(getComputedStyle(e).backgroundColor); if (b && b[3] > 0) { stack.push(b); if (b[3] >= 0.99) break; } e = e.parentElement; }
    var g = TOK['bg-0'].concat([1]);
    for (var i = stack.length - 1; i >= 0; i--) g = over(stack[i], g);
    return g;
  }
  var WORLD = '.sv-world--live, .sv-armed-pill, .tk-venue--live, .sv-venue--live, .sv-row--live > td:first-child';
  /* the data's own marks, counted apart as the board counts them: the
     signal dots' swatches and the levels' swatches in their keys are the
     chart's own drawings, in the chart's own tones */
  var DATA = '.sv-sig-sw, .sv-lvl-sw';
  var GLOW_OK = '.sv-live-dot, .status-dot.online, .sv-fresh--live, .sv-tab.is-active, .sv-seg-btn.is-active, .sv-dialog, .sv-popover, .sv-tb-menu, .sv-sig-card, .sr-popup';
  var REDS = [[204, 58, 64], [229, 72, 77], [255, 107, 110], [232, 48, 48]];
  var out = { n: 0, off: [], small: [], low: [], red: [], glow: [], grad: [] };
  function key(el) { var c = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).slice(0, 2).join('.');
    return el.tagName.toLowerCase() + (c ? '.' + c : el.id ? '#' + el.id : ''); }
  function push(list, el, prop, val, txt) { if (list.length < 60) list.push([key(el), prop, String(val), String(txt || '').slice(0, 40)]); }
  REGIONS.forEach(function (sel) {
    Array.prototype.forEach.call(document.querySelectorAll(sel), function (root) {
      [root].concat(Array.prototype.slice.call(root.querySelectorAll('*'))).forEach(function (el) {
        var tag = el.tagName.toLowerCase();
        if (/^(script|style|template|canvas|br|wbr|option|noscript)$/.test(tag)) return;
        if (el instanceof SVGElement && tag !== 'svg') return;
        if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
        var r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return;
        var cs = getComputedStyle(el);
        out.n++;
        var txt = '';
        for (var c0 = el.firstChild; c0; c0 = c0.nextSibling) if (c0.nodeType === 3) txt += c0.nodeValue;
        txt = txt.replace(/\s+/g, ' ').trim();
        var props = [['color', txt ? cs.color : null], ['background-color', cs.backgroundColor]];
        ['top', 'right', 'bottom', 'left'].forEach(function (s) {
          if (parseFloat(cs['border-' + s + '-width']) > 0 && cs['border-' + s + '-style'] !== 'none')
            props.push(['border-' + s + '-color', cs['border-' + s + '-color']]);
        });
        if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) props.push(['outline-color', cs.outlineColor]);
        props.forEach(function (p) {
          if (!p[1]) return;
          var c = parse(p[1]);
          if (!c || c[3] <= 0.004) return;
          if (!tokenish(c) && !el.matches(DATA)) push(out.off, el, p[0], p[1], txt);
        });
        if (txt) {
          if (parseFloat(cs.fontSize) < 10.95) push(out.small, el, 'font-size', cs.fontSize, txt);
          var fg = parse(cs.color);
          if (fg && fg[3] > 0.004 && !el.closest('[aria-hidden="true"] .sv-unused')) {
            var g = ground(el), f = over(fg, g);
            var L1 = lum(f), L2 = lum(g), k = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
            if (k < 4.5) push(out.low, el, 'contrast', k.toFixed(2), txt);
          }
        }
        var bg = parse(cs.backgroundColor);
        if (bg && bg[3] >= 0.9 && REDS.some(function (rd) { return dist(bg, rd) <= 40; }) && !el.matches(WORLD) && !el.matches(DATA))
          push(out.red, el, 'background-color', cs.backgroundColor, txt);
        ['box-shadow', 'text-shadow'].forEach(function (p) {
          var v = cs.getPropertyValue(p);
          if (!v || v === 'none') return;
          var blur = v.replace(/rgba?\([^)]*\)/g, '').match(/-?[\d.]+px/g) || [];
          var hasBlur = false;
          for (var i = 0; i + 2 < blur.length; i += (p === 'text-shadow' ? 3 : 4)) if (parseFloat(blur[i + 2]) > 0) hasBlur = true;
          if (hasBlur && !el.matches(GLOW_OK)) push(out.glow, el, p, v, txt);
        });
        if (/gradient/.test(cs.backgroundImage || '') && !el.matches('.sv-panel--hero')) push(out.grad, el, 'background-image', cs.backgroundImage.slice(0, 60), txt);
      });
    });
  });
  return JSON.stringify(out);
})(__TOK__, __REGIONS__)"""

REGIONS = [".page-content", "#railSigFacets", "#railSignalsBody"]


class _Desk:
    """One Chromium for the class: the page as a file, a tab per state."""

    def __init__(self, markup):
        self.tmp = tempfile.mkdtemp(prefix="sv-desk-v2-")
        self.path = pathlib.Path(self.tmp) / "instrument.html"
        self.path.write_text(markup, encoding="utf-8")
        self.chrome = _Chrome(CHROME)

    def close(self):
        try:
            self.chrome.close()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, width=1440, height=900):
        sid = self.chrome.page(width, height, False)
        self.chrome.open(sid, self.path.as_uri())
        self.js(sid, "var r = document.getElementById('signalsRail'); if (r) r.classList.add('open'); 0")
        for _ in range(80):
            if self.js(sid, "(function(){var h=window.svCharts&&svCharts['%s'];return h&&h.bars?h.bars().length:0})()" % ID):
                break
            time.sleep(0.1)
        time.sleep(2.0)                 # the first paints, the one price's line, the chips
        return sid

    def js(self, sid, expression):
        return self.chrome.eval(sid, expression)

    def probe(self, sid):
        return json.loads(self.js(sid, PROBE.replace("__ID__", ID)))

    def census(self, sid):
        return json.loads(self.js(sid, CENSUS.replace("__TOK__", json.dumps(token_rgb()))
                                .replace("__REGIONS__", json.dumps(REGIONS))))

    def move(self, sid, x, y):
        self.chrome.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, session=sid)
        time.sleep(0.25)

    def click(self, sid, x, y):
        for kind in ("mousePressed", "mouseReleased"):
            self.chrome.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                          "buttons": 1 if kind == "mousePressed" else 0,
                                                          "clickCount": 1}, session=sid)
        time.sleep(0.25)

    def key(self, sid, key, code, vk):
        for kind in ("rawKeyDown", "keyUp"):
            self.chrome.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code,
                                                        "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk},
                             session=sid)
        time.sleep(0.2)

    def pixels(self, sid, rect):
        from PIL import Image
        data = self.chrome.call("Page.captureScreenshot", {"format": "png", "clip": {
            "x": rect["x"], "y": rect["y"], "width": rect["w"], "height": rect["h"], "scale": 1}}, session=sid)["data"]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")


def _near(px, rgb, tol):
    return sum((a - b) ** 2 for a, b in zip(px, rgb)) <= tol * tol


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheDeskInChromiumTests(TestCase):
    """The page at 1440 x 900 (and 1280, 1920 for the toolbar), the rail
    open, the chart on its one-hour candles: the board's structure and
    geometry, measured."""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("desk_v2", password="x", is_staff=True, is_superuser=True)
        cls.book = F.seed_desk(user)
        client = Client()
        client.force_login(user)
        page = client.get(F.PAGE_URL, HTTP_HOST="127.0.0.1").content.decode("utf-8")
        payloads = {tf: F.chart_payload(client, tf) for tf in ("1h", "1d")}
        markup = F.file_page(page, payloads, base_dir=str(ROOT), lib=LIB, prefs={"tf": "1h"})
        desk = _Desk(markup)
        try:
            sid = desk.open(1440, 900)
            cls.rest = desk.probe(sid)
            cls.census = desk.census(sid)
            body = cls.rest["body"]
            cls.pane = desk.pixels(sid, body) if body else None
            # the pointer on a past bar, then away
            if body:
                desk.move(sid, body["x"] + body["w"] * 0.45, body["y"] + body["h"] * 0.4)
                cls.cross = desk.probe(sid)
                desk.move(sid, body["x"] - 120, body["y"] - 60)
                cls.left = desk.probe(sid)
            else:
                cls.cross = cls.left = cls.rest
            # each menu opened by its button, its controls in view
            cls.opened = {}
            for name in ("More", "Range", "Candles", "Indicators", "Levels", "Draw"):
                btn = [t for t in cls.rest["tools"] if t["menu"] and t["t"].startswith(name)]
                if not btn:
                    continue
                at = desk.js(sid, """(function () {
                    var b = Array.prototype.find.call(document.querySelectorAll('#%s-container [aria-haspopup="menu"]'),
                        function (e) { return e.innerText.trim().indexOf('%s') === 0; });
                    var r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()""" % (ID, name))
                desk.click(sid, at[0], at[1])
                got = desk.probe(sid)
                got["census"] = desk.census(sid)
                desk.key(sid, "Escape", "Escape", 27)
                got["after"] = desk.probe(sid)["menus"]
                cls.opened[name] = got
            cls.widths = {}
            for w, hgt in ((1280, 800), (1920, 1080)):
                sid2 = desk.open(w, hgt)
                cls.widths[w] = desk.probe(sid2)
        finally:
            desk.close()

    # ── the header ──────────────────────────────────────────────────────

    def test_the_header_is_one_52px_row_over_the_chart(self):
        ih, card = self.rest["ih"], self.rest["card"]
        self.assertIsNotNone(ih, "the header row (.sv-ih)")
        self.assertIsNotNone(card, "the chart card (.sv-chart-card)")
        self.assertAlmostEqual(ih["h"], 52, delta=2)
        self.assertLessEqual(ih["b"], card["y"] - 8)
        self.assertGreaterEqual(card["y"] - ih["b"], 8)
        self.assertLessEqual(card["y"] - ih["b"], 16)
        self.assertAlmostEqual(ih["w"], card["w"], delta=1)
        self.assertGreaterEqual(len(self.rest["ihRows"]), 5)
        for row in self.rest["ihRows"]:
            with self.subTest(row=row["t"]):
                self.assertLessEqual(row["h"], 20, "one line")
                self.assertLessEqual(row["sw"], row["cw"] + 1, "nothing cut")

    def test_the_header_keeps_every_group_inside_its_row_at_every_width(self):
        """The old sidebar with the rail open leaves the row 838 px at 1440
        and 684 px at 1280: what the chart already says folds, nothing
        leaves the row, the two sides stay whole inside it."""
        for w, got in [(1440, self.rest)] + sorted(self.widths.items()):
            with self.subTest(width=w):
                ih, fit = got["ih"], got["ihFit"]
                self.assertLessEqual(fit["sw"], fit["cw"] + 1, "nothing runs past the row")
                self.assertEqual(got["ihCut"], [], "no words cut short")
                for kid in got["ihKids"]:
                    self.assertGreaterEqual(kid["x"], ih["x"] - 0.5, kid["c"])
                    self.assertLessEqual(kid["r"], ih["r"] + 0.5, kid["c"])
                sides = got["ticket"]
                self.assertEqual(len(sides), 2)
                for b in sides:
                    self.assertGreaterEqual(b["x"], ih["x"])
                    self.assertLessEqual(b["r"], ih["r"])
                    self.assertGreaterEqual(b["w"], 90, "a side keeps its price whole")

    def test_the_header_says_the_day_his_position_the_feed_and_the_two_sides(self):
        text = self.rest["ihText"].lower()
        for words in ("day", "▼ short", "1.5", "+15.42", "+0.44r", "entry 2658.40",
                      "etoro", "spread"):
            self.assertIn(words, text)
        # the day's range off the chart's own candles (its word folds on a
        # narrow desk, its title keeps it)
        self.assertRegex(text, r"\d{4}\.\d{2}–\d{4}\.\d{2}")
        real = self.rest["ihReal"]
        self.assertIsNotNone(real, "the REAL chip on his position")
        self.assertEqual(real["bg"], "rgb(204, 58, 64)")
        sides = self.rest["ticket"]
        self.assertEqual(len(sides), 2)
        self.assertIn("2647.72", sides[0]["t"])
        self.assertIn("2648.12", sides[1]["t"])
        for b in sides:
            self.assertLessEqual(b["h"], 44)
            self.assertGreaterEqual(b["y"], self.rest["ih"]["y"])
            self.assertLessEqual(b["b"], self.rest["ih"]["b"])

    # ── the chart's frame ───────────────────────────────────────────────

    def test_the_chart_takes_the_height_of_the_screen(self):
        card, vh = self.rest["card"], self.rest["vh"]
        self.assertGreaterEqual(card["h"], 0.6 * vh)
        self.assertGreaterEqual(card["h"], 480)
        floor = self.rest["bottomChrome"] if self.rest["bottomChrome"] is not None else vh
        self.assertLessEqual(card["b"], floor + 1, "the card ends where the screen does")
        self.assertGreaterEqual(card["b"], floor - 24, "and does not stop short of it")
        for w, got in sorted(self.widths.items()):
            with self.subTest(width=w):
                self.assertGreaterEqual(got["card"]["h"], max(480, 0.6 * got["vh"]))

    def test_one_toolbar_row_of_36px(self):
        for w, got in [(1440, self.rest)] + sorted(self.widths.items()):
            with self.subTest(width=w):
                self.assertIsNotNone(got["toolbar"])
                self.assertAlmostEqual(got["toolbar"]["h"], 36, delta=1)
                self.assertEqual(got["toolRows"], 1)
        tools = self.rest["tools"]
        shown_tf = [t["tf"] for t in tools if t["tf"]]
        self.assertEqual(shown_tf, ["5min", "15min", "1h", "4h", "1d", "1wk"])
        self.assertEqual([t["t"] for t in tools if t["tf"]], ["5m", "15m", "1H", "4H", "D", "W"])
        menus = [t["t"].split()[0] for t in tools if t["menu"] == "menu"]
        self.assertEqual(menus, ["More", "Range", "Candles", "Indicators", "Levels", "Draw"])
        ctls = [t["ctl"] for t in tools if t["ctl"]]
        self.assertEqual(ctls, ["tall", "log", "fit", "fullscreen"])
        pressed = [t["t"] for t in tools if t["pressed"] == "true" and t["tf"]]
        self.assertEqual(pressed, ["1H"])

    def test_the_menus_hold_every_control_and_open_inside_the_card(self):
        menus = {m["id"].rsplit("-", 1)[-1]: m for m in self.rest["menus"]}
        self.assertEqual(sorted(menus), ["candles", "draw", "indicators", "levels", "more", "range"])
        self.assertEqual(menus["more"]["tf"], ["1min", "10min", "30min", "2h"])
        self.assertEqual(menus["range"]["tf"], ["1w", "1mo", "3m", "1y"])
        self.assertEqual(menus["candles"]["type"], ["candlestick", "heikin", "line", "area"])
        self.assertEqual(menus["indicators"]["ind"],
                         ["sma20", "sma50", "ema20", "bb", "vwap", "rsi", "macd", "volume"])
        self.assertEqual(menus["levels"]["ind"], ["positions", "levels"])
        self.assertEqual(menus["draw"]["tool"], ["crosshair", "hline", "trendline", "measure", "clear"])
        for m in self.rest["menus"]:
            self.assertFalse(m["shown"], "every menu shut at rest")
        self.assertEqual(sorted(self.opened), ["Candles", "Draw", "Indicators", "Levels", "More", "Range"])
        for name, got in sorted(self.opened.items()):
            with self.subTest(menu=name):
                shown = [m for m in got["menus"] if m["shown"]]
                self.assertEqual(len(shown), 1, "one menu open")
                self.assertFalse(any(m["shown"] for m in got["after"]), "Escape shuts it")
                c = got["census"]
                self.assertEqual(c["off"] + c["small"] + c["low"] + c["red"], [], "the open menu on tokens")

    # ── in the pane ─────────────────────────────────────────────────────

    def test_the_legend_sits_inside_the_pane_and_says_the_bar(self):
        for state in ("rest", "cross", "left"):
            got = getattr(self, state)
            with self.subTest(state=state):
                lg, body = got["legend"], got["body"]
                self.assertIsNotNone(lg, "the legend shows at rest too")
                self.assertGreaterEqual(lg["x"], body["x"])
                self.assertGreaterEqual(lg["y"], body["y"])
                self.assertLessEqual(lg["b"], body["y"] + 56)
                self.assertEqual(len(got["legendRows"]), 2)
                for row in got["legendRows"]:
                    self.assertLessEqual(row["h"], 20)
                text = got["legendText"]
                for words in ("O ", "H ", "L ", "C ", "1H", "eToro", "Vol", "next bar in"):
                    self.assertIn(words, text)
        self.assertIn("2647.72", self.rest["legendText"], "at rest: the last bar")
        self.assertNotEqual(self.cross["legendText"], self.rest["legendText"], "the pointer's bar")
        self.assertEqual(re.sub(r"next bar in \S+", "", self.left["legendText"]),
                         re.sub(r"next bar in \S+", "", self.rest["legendText"]), "back to the last bar")

    def test_rising_candles_hollow_falling_solid_in_the_data_red(self):
        o = self.rest["opts"]
        self.assertIsNotNone(o)
        self.assertEqual(o["bUp"].lower(), "#1fa374")
        self.assertEqual(o["wUp"].lower(), "#1fa374")
        self.assertEqual(o["down"].lower(), "#e5484d")
        self.assertEqual(o["bDown"].lower(), "#e5484d")
        self.assertEqual(o["wDown"].lower(), "#e5484d")
        m = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", o["up"].replace(" ", ""))
        self.assertTrue(m, o["up"])
        self.assertEqual(tuple(int(x) for x in m.groups()[:3]), UP_FILL)
        self.assertLessEqual(float(m.group(4)), 0.25, "a rising body is a wash: hollow")
        self.assertFalse(o["last"], "no second last-price box")

    def test_the_pane_paints_the_data_colours_and_no_old_one(self):
        img = self.pane
        self.assertIsNotNone(img)
        px = list(img.getdata())
        down = sum(1 for p in px if _near(p, DOWN_FILL, 6))
        up = sum(1 for p in px if _near(p, UP_FILL, 6))
        eye = sum(1 for p in px if _near(p, EYE, 40))
        gold = sum(1 for p in px if _near(p, OLD_GOLD, 30) or _near(p, OLD_GOLD2, 30))
        old_red = sum(1 for p in px if _near(p, OLD_RED, 12))
        self.assertGreater(down, 400, "falling bodies, solid")
        self.assertGreater(up, 150, "rising edges")
        self.assertLess(up, down, "a rising body is hollow: only its edge is up-fill")
        self.assertEqual((eye, gold, old_red), (0, 0, 0))

    def test_his_levels_wear_their_chips_and_none_sits_on_another(self):
        chips = self.rest["chips"]
        self.assertTrue(chips, "the level chips (.sv-mchip)")
        for i, a in enumerate(chips):
            for b in chips[i + 1:]:
                with self.subTest(a=a["t"], b=b["t"]):
                    overlap = min(a["r"], b["r"]) - max(a["x"], b["x"]) > 0 and \
                        min(a["b"], b["b"]) - max(a["y"], b["y"]) > 0
                    self.assertFalse(overlap)
        body = self.rest["body"]
        for c in chips:
            with self.subTest(chip=c["t"]):
                self.assertGreaterEqual(c["x"], body["x"])
                self.assertLessEqual(c["r"], body["r"])
                self.assertGreaterEqual(c["y"], body["y"] - 1)
                self.assertLessEqual(c["b"], body["b"] + 1)

    def test_the_entry_wears_the_real_chip(self):
        world = self.rest["world"]
        self.assertIsNotNone(world, "the REAL chip on the entry's line")
        self.assertEqual(world["bg"], "rgb(204, 58, 64)")
        y = self.rest["y"]["entry"]
        self.assertIsNotNone(y)
        mid = (world["b"]["y"] + world["b"]["b"]) / 2 - self.rest["body"]["y"]
        self.assertLessEqual(abs(mid - y), 14, "on its line")

    def test_a_level_off_the_view_pins_to_its_edge_with_its_distance(self):
        y, body = self.rest["y"], self.rest["body"]
        h = body["h"]
        off = {k: v for k, v in y.items() if v is not None and (v < 0 or v > h - 30)}
        edges = [c for c in self.rest["chips"] if c["edge"]]
        for name, v in sorted(off.items()):
            with self.subTest(level=name):
                side = "top" if v < 0 else "bottom"
                self.assertTrue(any(c["edge"] == side for c in edges), (name, v, edges))
        for c in edges:
            with self.subTest(chip=c["t"]):
                self.assertRegex(c["t"], r"[↑↓]")
                self.assertRegex(c["t"], r"\d+\.\d{2}\s*$")
        self.assertTrue(any("Your target" in c["t"] for c in self.rest["chips"]))

    def test_the_one_price_line_is_labelled_with_its_words_and_age(self):
        now = [c for c in self.rest["chips"] if "sv-mchip--now" in c["cls"]]
        self.assertEqual(len(now), 1)
        self.assertRegex(now[0]["t"], r"eToro \w+ · \d+ s")
        cap = self.rest["caption"]
        self.assertIsNotNone(cap)
        self.assertIn("eToro", cap["t"])

    def test_the_key_at_the_card_s_foot_and_the_credit_under_it(self):
        """The levels' key is the foot's first row, one line; the library's
        credit (its NOTICE whole, its link "Charts by TradingView" at the
        card's right edge, as the board draws it) is the foot's last line,
        never hidden."""
        for w, got in [(1440, self.rest)] + sorted(self.widths.items()):
            with self.subTest(width=w):
                key, card, credit = got["key"], got["card"], got["credit"]
                self.assertIsNotNone(key, "the key row shows")
                self.assertLessEqual(key["h"], 30, "one row")
                self.assertGreaterEqual(key["y"], got["body"]["b"] - 1, "under the pane")
                self.assertLessEqual(key["y"] - got["container"]["b"], 2, "the foot's first row")
                self.assertLessEqual(key["b"], card["b"])
                for a in got["keyKids"]:              # nothing in the row sits on another
                    for b in got["keyKids"]:
                        if a is not b:
                            self.assertFalse(min(a["r"], b["r"]) - max(a["x"], b["x"]) > 0.5
                                             and min(a["b"], b["b"]) - max(a["y"], b["y"]) > 0.5, (a, b))
                for words in ("Pools", "Swings", "Sessions", "Round numbers"):
                    self.assertIn(words, got["keyText"])
                self.assertIsNotNone(credit, "the credit, never hidden")
                self.assertEqual(got["creditText"].strip(), "Charts by TradingView")
                line = got["creditLine"]
                self.assertIsNotNone(line)
                self.assertLessEqual(line["h"], 26, "one line of 16 px and its padding")
                self.assertGreaterEqual(line["y"], key["b"] - 1, "under the key")
                self.assertLessEqual(line["b"], card["b"] + 1)
                self.assertGreaterEqual(credit["r"], card["r"] - 16, "at the card's right edge")
                for words in ("TradingView Lightweight Charts™", "Copyright (c) 2023 TradingView, Inc."):
                    self.assertIn(words, got["creditWords"])
        for words in ("your SL / TP solid", "signal dashed"):
            self.assertIn(words, self.widths[1920]["keyText"], "the money's key where the row has room")

    # ── no old marker; the money controls ──────────────────────────────

    def test_no_old_marker_on_the_page_or_the_rail(self):
        c = self.census
        self.assertGreater(c["n"], 150)
        for name in ("off", "small", "low", "red", "glow", "grad"):
            with self.subTest(marker=name):
                self.assertEqual(c[name], [])

    def test_the_money_controls_keep_their_words_forms_and_order(self):
        money = [m for m in self.rest["money"] if m[0] in ("tk-short", "tk-long")]
        self.assertEqual([tuple(m) for m in money], MONEY_ORDER)
        rail = [m[0] for m in self.rest["money"] if m[0].startswith("sr-pop")]
        self.assertEqual(rail, ["sr-pop-btn-act", "sr-pop-btn-pass"] * 5)
        forms = [f for f in self.rest["forms"] if f[0] and "watchlist" in f[0]]
        self.assertEqual(forms, [["/instruments/XAUUSD/watchlist/", "post",
                                  ["csrfmiddlewaretoken:hidden", "next:hidden", ":submit"]]])
