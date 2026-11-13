"""The frame and the menu, as the desk v2 board draws them (UI redo B1 + B2,
2026-11-13).

The operator approved the desk v2 boards with "amazing work, bravo, I need
it fast!!" (canvas_v2/project/Desk2.dc.html, the frame around the
positions; Twist2.dc.html, the Sauron twist close up; Instrument2.dc.html,
the frame with the menu folded to its icons). His two questions took their
defaults: the Horde replaces POSITIONS in the bottom bar.

What the board fixes, measured here in a headless Chromium on pages the
test client renders over a synthetic book (a REAL row at eToro with
eToro's own cells, a paper row, a hand-kept row, a signal on each side):

  * ONE BAND at the top: a 44 px top bar (the page title in Orbitron, the
    "/ Symbol or command" field, the clock, the sessions, the feed, REAL
    ARMED, the bell, the lock, the operator), then one 32 px band where the
    prices then the news scroll (static/js/sv-marquee.js keeps them).
  * CONTENT STARTS HIGH: the first content line at y <= 100, 16 px under
    the band; nothing floats over the page: Gollum, the Eye and the Horde
    sit in the bottom bar, Council, Activity and Ask Sauron in the right
    dock, the rail is a column that pushes the page.
  * A THIN BOTTOM BAR, 32 px, one scope said once: the REAL chip, then
    PORTFOLIO, OPEN P&L (the real book only), AT STOPS, MARGIN and
    DRAWDOWN; BOTS; the HORDE as one standard per seat in POSITIONS'
    place; "N more"; "? Keys". Gollum docked left, the Eye docked right.
    Nothing in it is hidden behind a scroll.
  * THE MENU: Rajdhani 600 rows of 32 px, Orbitron section heads that fold,
    one inline-SVG icon family (24-unit grid, 1.5 stroke, currentColor),
    no glyph for an icon; folded to 56 px it keeps the icons; the tower in
    the menu's empty foot only.
  * NO OLD MARKER in the frame: every colour a token, no text under 11 px,
    contrast at least 4.5:1, no glow but the wordmark's, REAL the only
    solid red fill.
  * THE KEYS: "/" goes to the command field, "?" opens the keys.

Display only: no order, no broker, no model, no network. Every row is
synthetic. The measured classes skip without a Chromium.

Run with:  python manage.py test tests.test_shell_frame_measured
"""
import json
import pathlib
import re
import unittest
import urllib.parse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, _legacy, _quote, _trade
from tests.test_design_tokens import PALETTE, contrast
from tests.test_magic_layer import _Browser, _file_page
from tests.test_ui_s0_fixes import _get

ROOT = pathlib.Path(settings.BASE_DIR)
BASE = "templates/base.html"
FRAME_CSS = "static/css/sv-frame.css"
FRAME_JS = "static/js/sv-frame.js"
ICONS = "templates/_partials/sv_icons.html"

POSITIONS, INSTRUMENT, PORTFOLIO = "/positions/", "/instruments/XAUUSD/", "/portfolio/"
#: The board's viewport, then the tiers either side of it (spec §6.1).
VIEWPORTS = ((1280, 800), (1440, 900), (1920, 1080), (2560, 1440))
#: The menu's width by tier, the rail's open width by tier (the board draws
#: 340 at 1440; 300 below it, 380 from 2200).
SIDE_W = {1280: 232, 1440: 232, 1920: 240, 2560: 256}
RAIL_W = {1280: 300, 1440: 340, 1920: 340, 2560: 380}
TOP_H, BAND_H, FOOT_H, DOCK_W, MINI_W = 44, 32, 32, 40, 56

#: The bottom bar, left to right, by the board.
CELLS = ("portfolio", "pnl", "stops", "margin", "drawdown", "bots", "horde", "more", "keys")
LABELS = {"portfolio": "PORTFOLIO", "pnl": "OPEN P&L", "stops": "AT STOPS", "margin": "MARGIN",
          "drawdown": "DRAWDOWN", "bots": "BOTS", "horde": "HORDE"}
#: The top bar, left to right.
TOPBAR = (".topbar-title", "form.sv-cmd", "#clock", ".exchange-indicator", "#liveStatusPill",
          ".sv-armed-pill", "#notifBell", "#lockNowBtn", "#userMenu")
#: The dock, top to bottom (Council and Activity are staff's, as their panels are).
DOCK = ("signals", "council", "activity", "ask")
#: The fixture's eToro cells: eToro's own equity and used margin.
EQUITY, USED = "10453.61", "4402.10"

#: Colours the frame may paint: the token sheet's (sv-tokens.css), dark.
TOKEN_RGB = {tuple(int(PALETTE[k].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)): k for k in PALETTE}
TEXT_OK = {"--sv-ink-1", "--sv-ink-2", "--sv-ink-3", "--sv-eye", "--sv-up", "--sv-down",
           "--sv-demo", "--sv-warn", "--sv-ai", "--sv-real-ink"}
REAL_RGB = (204, 58, 64)
#: The world family (§3.5): REAL's solid red belongs to these alone.
WORLD_FAMILY = (".sv-world--live", ".sv-armed-pill", ".sv-venue--live", ".sv-row--live",
                ".tk-venue--live", ".sv-sb-real")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _book(name):
    """A signed-in staff client over a synthetic book: eToro's own cells for
    a REAL account (equity 10,453.61, used 4,402.10), a REAL row at eToro, a
    paper row, a hand-kept row, a signal on each side."""
    from tests.test_signal_acted_and_sizing import _signal
    from tests.test_used_is_etoros import _cfg, _etoro, _row
    user = get_user_model().objects.create_user(name, password="x", is_staff=True, is_superuser=True)
    _signal(_quote("BTCUSD", 60600).instrument, direction="bullish", rule="frame_up")
    _signal(_quote("ETHUSD", 2600).instrument, direction="bearish", entry=2600, stop=2700,
            target=2400, rule="frame_down")
    _quote("XAUUSD", 2648.12, asset_class="commodity")
    _quote("AAPL", 227.06, asset_class="stock")
    _etoro(user, demo=False, used=USED, cash="6051.51", pnl="76.26", total=EQUITY,
           balance="10377.35", age_s=40)
    _row(_cfg(user, cls="stock", name="frame_live", mode="live"), "AAPL", 4, 228.10)
    _trade(user)
    _legacy(user)
    client = Client()
    client.force_login(user)
    return client


def _pages(client, urls):
    return {u: _file_page(_get(client, u), scripts=("sv-frame.js",)) for u in urls}


# ══════════════════════════════════════════════════════════════════════════
# The source: one family of icons, one sheet, the keys
# ══════════════════════════════════════════════════════════════════════════

class FrameSourceTests(SimpleTestCase):

    def test_the_frame_sheet_loads_after_the_kit_and_before_the_phone_tier(self):
        base = read(BASE)
        kit = base.index("css/sv-kit.css")
        frame = base.index("css/sv-frame.css")
        phone = base.index("css/sv-responsive.css")
        self.assertLess(kit, frame)
        self.assertLess(frame, phone)
        self.assertEqual(base.count("css/sv-frame.css"), 1)
        self.assertEqual(len(re.findall(r"<script\b[^>]*js/sv-frame\.js[^>]*\bdefer\b", base)), 1)

    def test_the_glyph_link_draws_the_arrows_the_figures_use(self):
        """Google's latin subsets lack ▲ ▼ ≈ ≥ → ↓: one link draws them in
        JetBrains Mono (the board's proposal, approved with it)."""
        base = read(BASE)
        links = [urllib.parse.unquote(l.replace("&amp;", "&"))
                 for l in re.findall(r'href="(https://fonts\.googleapis\.com/[^"]+)"', base)]
        glyphs = [l for l in links if "JetBrains+Mono" in l and "text=" in l]
        self.assertEqual(len(glyphs), 1, links)
        for ch in "▲▼≈≥→↓":
            self.assertIn(ch, glyphs[0])

    def test_every_symbol_is_one_family(self):
        icons = read(ICONS)
        symbols = re.findall(r"<symbol\b([^>]*)>", icons)
        self.assertGreaterEqual(len(symbols), 60)
        for attrs in symbols:
            with self.subTest(symbol=attrs[:40]):
                self.assertIn('viewBox="0 0 24 24"', attrs)
                self.assertIn('stroke="currentColor"', attrs)
                self.assertIn('stroke-width="1.5"', attrs)
                self.assertIn('fill="none"', attrs)
        # No child repaints a stroke or a fill of its own.
        self.assertNotRegex(icons, r"<(path|circle|rect|ellipse)\b[^>]*\b(stroke|fill|stroke-width)=")

    def test_every_nav_row_names_an_icon_the_sprite_has(self):
        base = read(BASE)
        ids = set(re.findall(r'<symbol id="(svi-[\w-]+)"', read(ICONS)))
        nav = base[base.index('<nav class="sidebar-nav"'):base.index("</nav>", base.index('<nav class="sidebar-nav"'))]
        rows = re.findall(r'<a href="[^"]*"[^>]*class="nav-link[^"]*"[^>]*>(.*?)</a>', nav, flags=re.S)
        self.assertGreaterEqual(len(rows), 55)
        for row in rows:
            with self.subTest(row=row[-60:]):
                icon = re.search(r'<span class="icon"[^>]*>(.*?)</span>', row, flags=re.S)
                self.assertTrue(icon, row)
                used = re.findall(r'<use href="#(svi-[\w-]+)"', icon.group(1))
                self.assertEqual(len(used), 1, row)
                self.assertIn(used[0], ids)
                # Nothing but the icon in it: no glyph, no emoji.
                self.assertEqual(re.sub(r"<[^>]+>", "", icon.group(1)).strip(), "")

    def test_the_frame_sheet_is_tokens_only(self):
        css = re.sub(r"/\*.*?\*/", "", read(FRAME_CSS), flags=re.S)
        # No literal colour but the light sources' own rgba(0,232,104,…)
        # (the Eye's light, the board's doses) and black shadows.
        for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b", css):
            self.fail("a literal colour in sv-frame.css: %s" % m.group(0))
        for m in re.finditer(r"rgba?\(([^)]*)\)", css):
            rgb = tuple(int(float(x)) for x in m.group(1).split(",")[:3])
            self.assertIn(rgb, ((0, 232, 104), (0, 0, 0), (220, 255, 235), (4, 30, 16)), m.group(0))
        for m in re.finditer(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", css):
            self.assertGreaterEqual(float(m.group(1)), 11, m.group(0))
        self.assertNotRegex(css, r"backdrop-filter\s*:(?!\s*none)")
        self.assertNotRegex(css, r"\.sv-armed-pill[^{]*\{[^}]*filter\s*:(?!\s*none)")

    def test_the_keys_are_the_frame_s(self):
        js = read(FRAME_JS)
        self.assertIn("'/'", js)
        self.assertIn("'?'", js)
        for never in ("fetch(", "XMLHttpRequest", "WebSocket", "htmx.ajax"):
            self.assertNotIn(never, js)

    def test_the_marquee_keeps_its_hooks_in_the_band(self):
        base = read(BASE)
        band = base[base.index('class="sv-band"'):base.index("<!-- Restore tabs")]
        self.assertRegex(band, r'<div class="data-headband" id="dataHeadband"[^>]*data-sv-marquee-speed="40"[^>]*data-sv-marquee-pop="\.dh-pop"')
        self.assertRegex(band, r'<div class="ticker-bar" id="tickerBar"[^>]*data-sv-marquee-speed="30"[^>]*data-sv-marquee-pop="\.ticker-popup"')
        self.assertLess(band.index('id="dataHeadband"'), band.index('class="sv-band-sep"'))
        self.assertLess(band.index('class="sv-band-sep"'), band.index('id="tickerBar"'))

    def test_the_money_controls_the_frame_carries_keep_their_words_and_hooks(self):
        """§10: REAL ARMED keeps its words and its door; the bar's
        POSITIONS list keeps its CLOSE with data-sv-close-trade (it waits
        in "N more", its look is B3's)."""
        base = read(BASE)
        self.assertIn('<a href="{% url \'asset_bots_dashboard\' %}" class="sv-armed-pill"', base)
        self.assertIn("<span>REAL MONEY</span><span class=\"sv-armed-words\">&middot; {{ panel_bot.live }} bot{{ panel_bot.live|pluralize }} armed</span>", base)
        self.assertIn('<button type="button" class="ip-pos-close" data-sv-close-trade="{{ t.id }}" title="Close this position">Close</button>', base)


# ══════════════════════════════════════════════════════════════════════════
# Measured: the frame as the browser lays it out
# ══════════════════════════════════════════════════════════════════════════

PROBE = r"""
(function () {
  function vis(el) {
    if (!el) return false;
    var cs = getComputedStyle(el), r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0 && r.width > 0 && r.height > 0;
  }
  function box(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    return { x: Math.round(r.left * 10) / 10, y: Math.round(r.top * 10) / 10, w: Math.round(r.width * 10) / 10,
             h: Math.round(r.height * 10) / 10, r: Math.round(r.right * 10) / 10, b: Math.round(r.bottom * 10) / 10, vis: vis(el) };
  }
  // The settled frame: the page's entrance animations run to their end.
  try { document.getAnimations().forEach(function (a) {
    var t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
    if (t && t.iterations !== Infinity) a.finish(); }); } catch (e) {}
  var q = function (s) { return document.querySelector(s); };
  var pc = q('.page-content');
  var first = null;
  if (pc) {
    var all = pc.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var r = all[i].getBoundingClientRect();
      if (r.height > 4 && r.width > 40 && getComputedStyle(all[i]).visibility !== 'hidden') { first = r.top; break; }
    }
  }
  var out = {
    vw: document.documentElement.clientWidth, vh: innerHeight,
    side: box(q('.sidebar')), brand: box(q('.sidebar-brand')), top: box(q('.topbar')),
    band: box(q('.sv-band')), prices: box(q('#dataHeadband')), news: box(q('#tickerBar')),
    sep: box(q('.sv-band-sep')), sepText: q('.sv-band-sep') ? q('.sv-band-sep').textContent.trim() : null,
    foot: box(q('.info-panel-wrap')), dock: box(q('.sv-dock')), rail: box(q('.signals-rail')),
    content: box(pc), first: first, gollum: box(q('#gollumFab')), eye: box(q('#seEyeFab')),
    tower: box(q('.sv-tower')), title: box(q('.topbar-title')),
    titleLines: q('.topbar-title') ? q('.topbar-title').getClientRects().length : 0,
    scroll: { w: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth },
  };
  out.topbar = __TOPBAR__.map(function (s) { var e = q('.topbar ' + s); return [s, box(e)]; });
  out.cells = __CELLS__.map(function (c) {
    var e = q('.info-panel-wrap [data-sv-cell="' + c + '"]');
    if (!e) return [c, null];
    var lab = e.querySelector('.ip-label');
    // Lines: the text's boxes grouped by their vertical centre (a label
    // and a figure of two sizes share a line; a wrap is a new one).
    var mids = [];
    var walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (!n.nodeValue.trim() || !vis(n.parentElement) || n.parentElement.closest('.ip-dropdown, .sv-more-pop')) continue;
      var rg = document.createRange(); rg.selectNodeContents(n);
      Array.prototype.forEach.call(rg.getClientRects(), function (rc) { if (rc.width > 0) mids.push((rc.top + rc.bottom) / 2); });
    }
    mids.sort(function (a, b) { return a - b; });
    var rows = [];
    mids.forEach(function (m) { if (!rows.length || m - rows[rows.length - 1] > 6) rows.push(m); });
    var text = '';
    var w2 = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    while (w2.nextNode()) {
      var n2 = w2.currentNode;
      if (!vis(n2.parentElement) || n2.parentElement.closest('.ip-dropdown, .sv-more-pop')) continue;
      text += n2.nodeValue;
    }
    return [c, { box: box(e), label: lab ? lab.textContent.trim() : null, lines: rows.length,
                 text: text.replace(/\s+/g, ' ').trim() }];
  });
  var real = q('.info-panel-wrap .sv-sb-real');
  out.realChip = real ? { box: box(real), bg: getComputedStyle(real).backgroundColor, text: real.textContent.trim() } : null;
  var bar = q('.info-panel-wrap .info-panel-scroll') || q('.info-panel-wrap');
  out.barScroll = bar ? { sw: bar.scrollWidth, cw: bar.clientWidth } : null;
  var flags = document.querySelectorAll('.info-panel-wrap [data-sv-cell="horde"] .sv-seat');
  out.flags = Array.prototype.map.call(flags, function (f) { return [f.getAttribute('data-world'), getComputedStyle(f).fill, getComputedStyle(f).stroke]; });
  out.dockBtns = Array.prototype.map.call(document.querySelectorAll('.sv-dock [data-sv-dock]'), function (b) {
    return [b.getAttribute('data-sv-dock'), box(b), b.getAttribute('aria-label') || ''];
  });
  out.floaters = ['#gollumFab', '#seEyeFab', '#svHordeTab', '#svCouncilBandTab', '#svActivityTab', '#railToggleBtn',
                  '#sidebarToggleBtn', '#ipRestorePill', '.ip-minimize-tab', '.hb-restore-tab.ticker', '.hb-restore-tab.data']
    .map(function (s) { return [s, box(q(s))]; });
  return JSON.stringify(out);
})()
""".replace("__TOPBAR__", json.dumps(TOPBAR)).replace("__CELLS__", json.dumps(CELLS))

MENU_PROBE = r"""
(function () {
  function vis(el) {
    if (!el) return false;
    var cs = getComputedStyle(el), r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  }
  var rows = [], secs = [];
  document.querySelectorAll('.sidebar-nav .nav-link').forEach(function (a) {
    var cs = getComputedStyle(a), r = a.getBoundingClientRect(), ico = a.querySelector('.icon svg.sv-ico');
    var use = ico && ico.querySelector('use');
    var ref = use ? (use.getAttribute('href') || '').slice(1) : null;
    var ics = ico ? getComputedStyle(ico) : null;
    var label = a.querySelector('.label-text');
    rows.push({ text: (label ? label.textContent : a.textContent).trim(), vis: vis(a), h: r.height, x: r.left, w: r.width,
                face: cs.fontFamily, size: cs.fontSize, weight: cs.fontWeight,
                icon: !!ico, ref: ref, has: !!(ref && document.getElementById(ref)),
                iconVis: vis(ico), iconBox: ico ? [ico.getBoundingClientRect().left, ico.getBoundingClientRect().width] : null,
                stroke: ics ? ics.stroke : null, color: ics ? ics.color : null, sw: ics ? ics.strokeWidth : null, fill: ics ? ics.fill : null,
                labelVis: label ? vis(label) : false,
                labelBox: label ? [label.getBoundingClientRect().width, label.getBoundingClientRect().height] : null,
                labelShown: label ? getComputedStyle(label).display !== 'none' && getComputedStyle(label).visibility !== 'hidden' : false,
                iconText: a.querySelector('.icon') ? a.querySelector('.icon').textContent.trim() : null,
                sec: (function () { var n = a.previousElementSibling; while (n && !n.classList.contains('nav-section')) n = n.previousElementSibling; return n ? n.getAttribute('data-nav-sec') : null; })(),
                active: a.classList.contains('active') });
  });
  document.querySelectorAll('.sidebar-nav .nav-section').forEach(function (s) {
    var cs = getComputedStyle(s), r = s.getBoundingClientRect(), b = s.querySelector('button.nav-fold');
    secs.push({ key: s.getAttribute('data-nav-sec'), vis: vis(s), h: r.height, face: cs.fontFamily, size: cs.fontSize,
                button: !!b, expanded: b ? b.getAttribute('aria-expanded') : null, text: s.textContent.trim() });
  });
  var tower = document.querySelector('.sv-tower'), tb = tower ? tower.getBoundingClientRect() : null;
  var hits = [];
  if (tb) document.querySelectorAll('.sidebar-nav .nav-link, .sidebar-nav .nav-section').forEach(function (e) {
    if (!vis(e)) return;
    var r = e.getBoundingClientRect();
    if (r.right > tb.left && r.left < tb.right && r.bottom > tb.top && r.top < tb.bottom) hits.push(e.textContent.trim());
  });
  var tp = tower ? tower.querySelector('path') : null;
  return JSON.stringify({ rows: rows, secs: secs, towerHits: hits,
    towerOpacity: tp ? parseFloat(getComputedStyle(tp).fillOpacity) : null,
    side: document.querySelector('.sidebar').getBoundingClientRect().width,
    sideBottom: document.querySelector('.sidebar').getBoundingClientRect().bottom,
    towerBox: tb ? [tb.left, tb.top, tb.right, tb.bottom] : null });
})()
"""

#: Every visible element of the frame's regions: its colours, size,
#: shadow and ground.
LOOK_PROBE = r"""
(function () {
  function rgba(s) { var m = /rgba?\(([^)]+)\)/.exec(s || ''); if (!m) return null; var p = m[1].split(',').map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
  function vis(el) {
    var cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.display === 'none' || cs.visibility === 'hidden' || r.width === 0 || r.height === 0) return false;
    for (var p = el; p; p = p.parentElement) if (parseFloat(getComputedStyle(p).opacity) === 0) return false;
    return r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
  }
  function ground(el) {
    for (var p = el; p; p = p.parentElement) { var c = rgba(getComputedStyle(p).backgroundColor); if (c && c[3] >= 0.99) return c; }
    return [4, 11, 7, 1];
  }
  function name(el) { return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && el.className.baseVal === undefined && el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : ''); }
  var regions = ['.sidebar', '.topbar', '.sv-band', '.info-panel-wrap', '.sv-dock', '#gollumFab', '#seEyeFab'];
  var out = [];
  regions.forEach(function (sel) {
    var root = document.querySelector(sel);
    if (!root) return;
    [root].concat(Array.prototype.slice.call(root.querySelectorAll('*'))).forEach(function (el) {
      if (el.closest('.ip-dropdown, .dh-pop, .ticker-popup, .sv-more-pop, .user-menu-dropdown, .notif-dropdown, .exchange-dropdown, .lsp-dropdown, svg, .sv-sprite')) return;
      if (!vis(el)) return;
      var cs = getComputedStyle(el), own = '';
      for (var k = 0; k < el.childNodes.length; k++) if (el.childNodes[k].nodeType === 3) own += el.childNodes[k].nodeValue;
      own = own.trim();
      out.push({ n: name(el), region: sel, text: own.slice(0, 24), color: rgba(cs.color), bg: rgba(cs.backgroundColor),
                 bgImage: cs.backgroundImage, ground: ground(el), size: parseFloat(cs.fontSize),
                 border: [cs.borderTopWidth, cs.borderTopColor, cs.borderBottomWidth, cs.borderBottomColor,
                          cs.borderLeftWidth, cs.borderLeftColor, cs.borderRightWidth, cs.borderRightColor],
                 shadow: cs.boxShadow, tshadow: cs.textShadow, filter: cs.filter, backdrop: cs.backdropFilter || '',
                 brand: !!el.closest('.sidebar-brand h1'),
                 real: !!el.closest(__WORLD__) });
    });
  });
  return JSON.stringify(out);
})()
""".replace("__WORLD__", json.dumps(", ".join(WORLD_FAMILY)))


def _near(rgb, target, tol=2):
    return all(abs(a - b) <= tol for a, b in zip(rgb[:3], target))


def _token(rgb):
    for t, name in TOKEN_RGB.items():
        if _near(rgb, t):
            return name
    if _near(rgb, (255, 255, 255)):
        return "--sv-real-ink"
    return None


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(c)) for c in rgb[:3])


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameGeometryTests(TestCase):
    """The board's geometry at 1440 x 900, and the same frame at the tiers
    either side: 1280, 1920, 2560, with the rail shut and open, and the
    menu folded to its icons."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_geo")
        pages = _pages(client, (POSITIONS, INSTRUMENT, PORTFOLIO))
        b = _Browser(pages, "sv-frame-geo-")
        cls.got, cls.menu = {}, {}
        try:
            for width, height in VIEWPORTS:
                sid = b.tab(width, height)
                for url in (POSITIONS, INSTRUMENT, PORTFOLIO):
                    b.open(sid, url, "try { localStorage.clear(); } catch (e) {}")
                    b.open(sid, url)
                    cls.got[(url, width, "shut")] = json.loads(b.js(sid, PROBE))
                    if url == POSITIONS:
                        cls.menu[width] = json.loads(b.js(sid, MENU_PROBE))
                    b.js(sid, "document.getElementById('signalsRail').classList.add('open'); 0")
                    cls.got[(url, width, "rail")] = json.loads(b.js(sid, PROBE))
                    b.js(sid, "document.getElementById('signalsRail').classList.remove('open');"
                              " document.getElementById('mainSidebar').classList.add('mini'); 0")
                    cls.got[(url, width, "mini")] = json.loads(b.js(sid, PROBE))
                    if url == POSITIONS and width == 1440:
                        cls.menu["mini"] = json.loads(b.js(sid, MENU_PROBE))
                    b.js(sid, "document.getElementById('mainSidebar').classList.remove('mini'); 0")
        finally:
            b.close()

    def each(self, state=None):
        for (url, width, st), got in sorted(self.got.items()):
            if state and st != state:
                continue
            yield (url, width, st), got

    def test_the_top_bar_and_the_band(self):
        for key, g in self.each("shut"):
            with self.subTest(at=key):
                side = SIDE_W[key[1]]
                self.assertEqual((g["top"]["x"], g["top"]["y"], g["top"]["h"], g["top"]["r"]),
                                 (side, 0, TOP_H, g["vw"]))
                self.assertTrue(g["band"] and g["band"]["vis"], "no band")
                self.assertEqual((g["band"]["x"], g["band"]["y"], g["band"]["h"], g["band"]["r"]),
                                 (side, TOP_H, BAND_H, g["vw"]))
                # Prices, then the news, in the one band, each its own lane.
                self.assertEqual((g["prices"]["y"], g["prices"]["h"]), (TOP_H, BAND_H))
                self.assertEqual((g["news"]["y"], g["news"]["h"]), (TOP_H, BAND_H))
                self.assertLess(g["prices"]["r"], g["sep"]["x"] + 1)
                self.assertLess(g["sep"]["r"], g["news"]["x"] + 1)
                self.assertGreater(g["prices"]["w"], g["news"]["w"])
                self.assertEqual(g["sepText"].upper(), "NEWS")

    def test_the_top_bar_reads_left_to_right_on_one_line(self):
        for key, g in self.each("shut"):
            with self.subTest(at=key):
                xs = []
                for sel, bx in g["topbar"]:
                    self.assertTrue(bx and bx["vis"], "%s is not in the top bar" % sel)
                    self.assertGreaterEqual(bx["y"], 0)
                    self.assertLessEqual(bx["b"], TOP_H)
                    xs.append(bx["x"])
                self.assertEqual(xs, sorted(xs), g["topbar"])
                self.assertEqual(g["titleLines"], 1)
                self.assertLessEqual(g["title"]["h"], 24)

    def test_content_starts_high(self):
        for key, g in self.each():
            with self.subTest(at=key):
                self.assertIsNotNone(g["first"])
                self.assertLessEqual(g["first"], 100)
                # Never under the band (a page may lift its own head into
                # the gutter; that is the page's batch).
                self.assertGreaterEqual(g["first"], TOP_H + BAND_H)

    def test_the_menu_column(self):
        for key, g in self.each():
            with self.subTest(at=key):
                w = MINI_W if key[2] == "mini" else SIDE_W[key[1]]
                self.assertEqual((g["side"]["x"], g["side"]["y"], g["side"]["w"]), (0, 0, w))
                self.assertEqual(g["side"]["b"], g["vh"] - FOOT_H)
                self.assertEqual(g["brand"]["h"], TOP_H)
                self.assertEqual(g["content"]["x"], w)

    def test_the_bottom_bar_is_thin_whole_and_full_width(self):
        for key, g in self.each():
            with self.subTest(at=key):
                f = g["foot"]
                self.assertEqual((f["x"], f["r"], f["h"], f["b"]), (0, g["vw"], FOOT_H, g["vh"]))
                # Nothing hidden behind a scroll, no cell past the Eye.
                self.assertLessEqual(g["barScroll"]["sw"], g["barScroll"]["cw"] + 1)
                eye = g["eye"]
                self.assertTrue(eye and eye["vis"])
                for name, cell in g["cells"]:
                    self.assertIsNotNone(cell, name)
                    self.assertTrue(cell["box"]["vis"], name)
                    self.assertLessEqual(cell["box"]["r"], eye["x"], name)
                    self.assertGreaterEqual(cell["box"]["y"], g["vh"] - FOOT_H - 0.5, name)
                    self.assertLessEqual(cell["box"]["b"], g["vh"] + 0.5, name)
                    self.assertEqual(cell["lines"], 1, "%s wraps: %r" % (name, cell["text"]))
                xs = [cell["box"]["x"] for _n, cell in g["cells"]]
                self.assertEqual(xs, sorted(xs))
                self.assertEqual(g["scroll"]["w"], g["scroll"]["cw"])

    def test_gollum_left_and_the_eye_right_in_the_bar(self):
        for key, g in self.each():
            with self.subTest(at=key):
                gl, eye = g["gollum"], g["eye"]
                self.assertTrue(gl["vis"])
                self.assertEqual(gl["x"], 0)
                self.assertGreaterEqual(gl["y"], g["vh"] - FOOT_H - 0.5)
                self.assertLessEqual(gl["r"], 46.5)
                self.assertLessEqual(gl["b"], g["vh"] + 0.5)
                self.assertEqual((eye["w"], eye["h"]), (26, 26))
                self.assertGreaterEqual(eye["y"], g["vh"] - FOOT_H)
                self.assertLessEqual(eye["r"], g["vw"])
                self.assertGreaterEqual(eye["r"], g["vw"] - 12)
                real = g["realChip"]
                self.assertTrue(real and real["box"]["vis"])
                self.assertLess(gl["r"], real["box"]["x"] + 0.5)

    def test_the_dock_and_the_rail_column(self):
        for key, g in self.each():
            with self.subTest(at=key):
                d = g["dock"]
                self.assertTrue(d and d["vis"])
                self.assertEqual((d["r"], d["w"], d["y"], d["b"]),
                                 (g["vw"], DOCK_W, TOP_H + BAND_H, g["vh"] - FOOT_H))
                names = [n for n, _b, _l in g["dockBtns"]]
                self.assertEqual(names, list(DOCK))
                for n, bx, label in g["dockBtns"]:
                    self.assertEqual((bx["w"], bx["h"]), (30, 30), n)
                    self.assertTrue(label, n)
                if key[2] == "rail":
                    r = g["rail"]
                    self.assertTrue(r["vis"])
                    self.assertEqual((r["r"], r["w"], r["y"], r["b"]),
                                     (g["vw"] - DOCK_W, RAIL_W[key[1]], TOP_H + BAND_H, g["vh"] - FOOT_H))
                    # The rail pushes the page: nothing of it under the rail.
                    self.assertLessEqual(g["content"]["r"], r["x"])
                else:
                    self.assertFalse(g["rail"]["vis"])
                    self.assertEqual(g["content"]["r"], g["vw"] - DOCK_W)

    def test_nothing_floats_over_the_page(self):
        for key, g in self.each():
            with self.subTest(at=key):
                c = g["content"]
                inner = (c["x"], TOP_H + BAND_H, c["r"], g["vh"] - FOOT_H)
                for sel, bx in g["floaters"]:
                    if not bx or not bx["vis"]:
                        continue
                    hit = bx["r"] > inner[0] and bx["x"] < inner[2] and bx["b"] > inner[1] and bx["y"] < inner[3]
                    self.assertFalse(hit, "%s floats over the page at %r" % (sel, bx))

    def test_the_menu_rows_and_heads(self):
        for width in (1440, 1920):
            m = self.menu[width]
            with self.subTest(width=width):
                shown = [r for r in m["rows"] if r["vis"]]
                self.assertGreaterEqual(len(shown), 10)
                for r in shown:
                    self.assertEqual(r["h"], 32, r["text"])
                    self.assertTrue(r["face"].startswith("Rajdhani"), r["face"])
                    self.assertEqual((r["size"], r["weight"]), ("15px", "600"), r["text"])
                for s in m["secs"]:
                    self.assertTrue(s["button"], s["key"])
                    if s["vis"]:
                        self.assertEqual(s["h"], 28, s["key"])
                        self.assertTrue(s["face"].startswith("Orbitron"), s["face"])
                        self.assertEqual(s["size"], "11px")

    def test_one_icon_family_and_no_glyph(self):
        m = self.menu[1440]
        for r in m["rows"]:
            with self.subTest(row=r["text"]):
                self.assertTrue(r["icon"] and r["has"], r)
                self.assertEqual(r["iconText"], "")
                if r["vis"]:
                    self.assertTrue(r["iconVis"])
                    self.assertEqual(r["stroke"], r["color"])
                    self.assertEqual((r["sw"], r["fill"]), ("1.5px", "none"))

    def test_the_sections_fold_and_the_page_s_own_stays_open(self):
        m = self.menu[1440]
        exp = {s["key"]: s["expanded"] for s in m["secs"]}
        self.assertEqual(exp.get("amon-hen"), "true")
        self.assertEqual(exp.get("the-book"), "true")
        for key in ("what-can-act", "what-is-measured", "what-is-invented", "the-markets", "the-machine", "you"):
            self.assertEqual(exp.get(key), "false", key)
        for r in m["rows"]:
            with self.subTest(row=r["text"]):
                self.assertEqual(r["vis"], exp[r["sec"]] == "true")
        active = [r for r in m["rows"] if r["active"]]
        self.assertEqual([r["text"] for r in active], ["Positions"])

    def test_the_folded_menu_keeps_its_icons(self):
        m = self.menu["mini"]
        self.assertEqual(m["side"], MINI_W)
        for r in m["rows"]:
            if not r["vis"]:
                continue
            with self.subTest(row=r["text"]):
                # The word leaves the eye (a box of at most 1 px) but never
                # the row: it stays rendered, the link's name for a screen
                # reader and the hover tip's text.
                self.assertLessEqual(max(r["labelBox"]), 1)
                self.assertTrue(r["labelShown"])
                self.assertTrue(r["text"])
                self.assertTrue(r["iconVis"])
                left, w = r["iconBox"]
                self.assertAlmostEqual(left + w / 2, MINI_W / 2, delta=1)

    def test_the_tower_watches_the_empty_foot_only(self):
        m = self.menu[1440]
        self.assertIsNotNone(m["towerBox"])
        self.assertEqual(m["towerHits"], [])
        self.assertAlmostEqual(m["towerOpacity"], 0.075, places=3)
        self.assertLessEqual(m["sideBottom"] - m["towerBox"][3], 16)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameFiguresTests(TestCase):
    """The bottom bar's REAL scope with the fixture's own eToro cells, the
    Horde's standards, the dock's counts."""

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_figs")
        pages = _pages(client, (POSITIONS,))
        b = _Browser(pages, "sv-frame-figs-")
        try:
            sid = b.tab(1440, 900)
            b.open(sid, POSITIONS)
            cls.g = json.loads(b.js(sid, PROBE))
        finally:
            b.close()

    def cell(self, name):
        return dict(self.g["cells"])[name]

    def test_one_scope_said_once(self):
        real = self.g["realChip"]
        self.assertEqual(real["text"].upper(), "REAL")
        self.assertTrue(_near([int(x) for x in re.findall(r"\d+", real["bg"])[:3]], REAL_RGB))
        for name, label in LABELS.items():
            self.assertEqual(self.cell(name)["label"].upper(), label)

    def test_the_real_book_s_figures(self):
        self.assertIn("10,453.61", self.cell("portfolio")["text"])
        self.assertIn("42.1%", self.cell("margin")["text"])
        self.assertRegex(self.cell("pnl")["text"], r"OPEN P&L\s*([+−-][\d,.]+|—)")
        self.assertRegex(self.cell("more")["text"], r"^\d+ more$")
        self.assertIn("Keys", self.cell("keys")["text"])

    def test_the_horde_stands_one_standard_per_seat_real_first(self):
        flags = self.g["flags"]
        self.assertGreaterEqual(len(flags), 2)
        self.assertLessEqual(len(flags), 8)
        worlds = [w for w, _f, _s in flags]
        order = {"live": 0, "demo": 1, "paper": 2, "none": 3}
        self.assertEqual(worlds, sorted(worlds, key=order.get))
        self.assertEqual(worlds[0], "live")
        self.assertTrue(_near([int(x) for x in re.findall(r"\d+", flags[0][1])[:3]], REAL_RGB))
        self.assertRegex(self.cell("horde")["text"], r"\d+ seats?")


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameLookTests(TestCase):
    """No old marker in the frame at 1440 x 900, dark, Magic: every colour a
    token, no text under 11 px, contrast at least 4.5:1, no glow but the
    wordmark's, REAL the only solid red fill, REAL ARMED never filtered."""

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_look")
        pages = _pages(client, (POSITIONS, INSTRUMENT))
        b = _Browser(pages, "sv-frame-look-")
        cls.got = {}
        try:
            sid = b.tab(1440, 900)
            for url in (POSITIONS, INSTRUMENT):
                b.open(sid, url)
                cls.got[url] = json.loads(b.js(sid, LOOK_PROBE))
            b.open(sid, POSITIONS)
            b.force(sid, ".sv-armed-pill", (":hover",))
            cls.armed = json.loads(b.js(sid, "(function () { var a = document.querySelector('.sv-armed-pill');"
                                             " if (!a) return 'null'; var cs = getComputedStyle(a);"
                                             " return JSON.stringify({bg: cs.backgroundColor, color: cs.color,"
                                             " filter: cs.filter, shadow: cs.boxShadow, face: cs.fontFamily}); })()"))
        finally:
            b.close()

    def each(self):
        for url, els in sorted(self.got.items()):
            for el in els:
                yield url, el

    def test_every_colour_is_a_token(self):
        bad = []
        for url, el in self.each():
            if el["text"] and el["color"] and _token(el["color"]) not in TEXT_OK:
                bad.append((url, el["n"], "color", _hex(el["color"])))
            if el["bg"] and el["bg"][3] >= 0.99 and not _token(el["bg"]):
                bad.append((url, el["n"], "background", _hex(el["bg"])))
            b = el["border"]
            for i in range(0, 8, 2):
                if float(b[i].rstrip("px") or 0) > 0:
                    c = [float(x) for x in re.findall(r"[\d.]+", b[i + 1])]
                    if len(c) >= 3 and (len(c) < 4 or c[3] >= 0.99) and not _token(c):
                        bad.append((url, el["n"], "border", _hex(c)))
        self.assertEqual(bad, [])

    def test_no_text_under_11px_and_every_text_reads(self):
        small, faint = [], []
        for url, el in self.each():
            if not el["text"]:
                continue
            if el["size"] < 11:
                small.append((url, el["n"], el["text"], el["size"]))
            if el["color"]:
                c = contrast(_hex(el["color"]), _hex(el["ground"]))
                if c < 4.5:
                    faint.append((url, el["n"], el["text"], round(c, 2)))
        self.assertEqual(small, [])
        self.assertEqual(faint, [])

    def test_no_glow_but_the_wordmark_s(self):
        lit = []
        for url, el in self.each():
            # The wordmark's own glow, which its line inherits.
            if el["tshadow"] not in ("none", "") and not el["brand"]:
                lit.append((url, el["n"], "text-shadow", el["tshadow"]))
            if el["filter"] not in ("none", ""):
                lit.append((url, el["n"], "filter", el["filter"]))
            if el["backdrop"] not in ("none", ""):
                lit.append((url, el["n"], "backdrop", el["backdrop"]))
        self.assertEqual(lit, [])

    def test_real_is_the_only_solid_red_fill(self):
        reds = []
        for url, el in self.each():
            bg = el["bg"]
            if bg and bg[3] >= 0.99 and bg[0] > 150 and bg[1] < 110 and bg[2] < 120 and not el["real"]:
                reds.append((url, el["n"], _hex(bg)))
        self.assertEqual(reds, [])

    def test_real_armed_is_a_flat_red_under_the_hand(self):
        a = self.armed
        self.assertIsNotNone(a)
        self.assertTrue(_near([int(x) for x in re.findall(r"\d+", a["bg"])[:3]], REAL_RGB))
        self.assertEqual(a["filter"], "none")
        self.assertFalse(a["face"].startswith("Orbitron"))


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameKeysTests(TestCase):
    """"/" goes to the command field, Esc leaves it; "?" opens the keys;
    the field reads a symbol, a page or a search."""

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_keys")
        pages = _pages(client, (POSITIONS,))
        b = _Browser(pages, "sv-frame-keys-")
        cls.got = {}
        try:
            sid = b.tab(1440, 900)
            b.open(sid, POSITIONS)
            c = b.chrome

            def key(k, code, vk, mods=0):
                for kind in ("rawKeyDown", "char", "keyUp"):
                    if kind == "char" and len(k) != 1:
                        continue
                    p = {"type": kind, "key": k, "code": code, "windowsVirtualKeyCode": vk,
                         "nativeVirtualKeyCode": vk, "modifiers": mods}
                    if kind == "char":
                        p["text"] = k
                    c.call("Input.dispatchKeyEvent", p, session=sid)
            key("/", "Slash", 191)
            cls.got["slash"] = b.js(sid, "document.activeElement ? document.activeElement.id : ''")
            cls.got["typed"] = b.js(sid, "document.getElementById('svCmd').value")
            key("Escape", "Escape", 27)
            cls.got["esc"] = b.js(sid, "document.activeElement ? document.activeElement.id : ''")
            key("?", "Slash", 191, 8)
            cls.got["keys"] = b.js(sid, "document.getElementById('kbdModalOverlay').classList.contains('open')")
            cls.got["targets"] = json.loads(b.js(sid, "JSON.stringify(['xauusd', 'Positions', 'gold miners']"
                                                      ".map(function (v) { return window.SVFrame ? SVFrame.target(v) : null; }))"))
            b.js(sid, "document.getElementById('kbdModalOverlay').classList.remove('open'); 0")
            b.js(sid, "document.querySelector('[data-sv-cell=\"keys\"]').click(); 0")
            cls.got["keysBtn"] = b.js(sid, "document.getElementById('kbdModalOverlay').classList.contains('open')")
            cls.got["fold"] = b.js(sid, "(function () { var s = document.querySelector('.nav-section[data-nav-sec=\"the-markets\"] button.nav-fold');"
                                        " s.click(); return s.getAttribute('aria-expanded'); })()")
            b.open(sid, POSITIONS)
            cls.got["kept"] = b.js(sid, "document.querySelector('.nav-section[data-nav-sec=\"the-markets\"] button.nav-fold').getAttribute('aria-expanded')")
            b.js(sid, "try { localStorage.clear(); } catch (e) {} 0")
        finally:
            b.close()

    def test_slash_goes_to_the_command_field(self):
        self.assertEqual(self.got["slash"], "svCmd")
        self.assertEqual(self.got["typed"], "")
        self.assertNotEqual(self.got["esc"], "svCmd")

    def test_question_mark_opens_the_keys(self):
        self.assertTrue(self.got["keys"])
        self.assertTrue(self.got["keysBtn"])

    def test_the_field_reads_a_symbol_a_page_or_a_search(self):
        sym, page, search = self.got["targets"]
        self.assertEqual(sym, "/instruments/XAUUSD/")
        self.assertEqual(page, "/positions/")
        self.assertEqual(search, "/instruments/?q=gold%20miners")

    def test_a_section_he_opens_stays_open(self):
        self.assertEqual(self.got["fold"], "true")
        self.assertEqual(self.got["kept"], "true")


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class PhoneTierUnchangedTests(TestCase):
    """At 390 the phone tier is the phone's: the menu off canvas, no dock,
    no band, no bottom bar, the phone nav at the foot."""

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_phone")
        pages = _pages(client, (POSITIONS,))
        b = _Browser(pages, "sv-frame-phone-")
        try:
            sid = b.chrome.page(390, 844, True)
            b.chrome.call("DOM.enable", session=sid)
            b.chrome.call("CSS.enable", session=sid)
            b.open(sid, POSITIONS)
            cls.g = json.loads(b.js(sid, "(function () { function v(s) { var e = document.querySelector(s); if (!e) return null;"
                                         " var cs = getComputedStyle(e), r = e.getBoundingClientRect();"
                                         " return {shown: cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.right > 0 && r.left < innerWidth, x: r.left, w: r.width}; }"
                                         " return JSON.stringify({side: v('.sidebar'), dock: v('.sv-dock'), foot: v('.info-panel-wrap'),"
                                         " nav: v('.sv-phone-nav'), scroll: document.documentElement.scrollWidth, vw: innerWidth}); })()"))
        finally:
            b.close()

    def test_the_phone_keeps_its_tier(self):
        g = self.g
        self.assertFalse(g["side"]["shown"])
        self.assertFalse(g["dock"] and g["dock"]["shown"])
        self.assertFalse(g["foot"]["shown"])
        self.assertTrue(g["nav"]["shown"])
        self.assertLessEqual(g["scroll"], g["vw"])
