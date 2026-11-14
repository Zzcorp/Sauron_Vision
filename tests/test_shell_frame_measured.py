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

    def test_every_icon_carries_its_symbol_s_view_box(self):
        """An icon's <svg> states the coordinate space of the symbol it
        draws, so its geometry is its own and not whatever its CSS box is
        that render (#115's CI, 2026-11-14: tests/test_chart_surfaces.py's
        ViewBoxTests found 101 <svg> with no viewBox, the icons and the
        sprite). It is the symbol's own viewBox, so the drawing maps one to
        one, as it did; the sprite, a 0 x 0 box, states the same grid."""
        base = read(BASE)
        boxes = dict(re.findall(r'<symbol id="(svi-[\w-]+)" viewBox="([^"]+)"', read(ICONS)))
        icons = re.findall(r'<svg class="sv-ico[^"]*"([^>]*)><use href="#(svi-[\w-]+)"/></svg>', base)
        self.assertGreaterEqual(len(icons), 90)
        self.assertEqual(len(icons), base.count('<svg class="sv-ico'))
        for attrs, ref in icons:
            with self.subTest(icon=ref):
                self.assertIn(ref, boxes)
                self.assertIn(' viewBox="%s"' % boxes[ref], attrs)
        self.assertRegex(read(ICONS), r'<svg class="sv-sprite"[^>]* viewBox="0 0 24 24"')

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
            b.force(sid, ".sv-armed-pill", ("hover",))
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


# ══════════════════════════════════════════════════════════════════════════
# The review of the build (2026-11-13), measured first. Each class below
# was red on aeb45ae (scratchpad ui_b1/fix/red_*.log) and pins what the
# review found, in the operator's words: "amazing work, bravo, I need it
# fast!!" approved the desk v2 board, and these are the places the build
# fell short of it or of §10.
# ══════════════════════════════════════════════════════════════════════════

#: A machine face at least as wide as Orbitron 600 on every page name the
#: bar shows (measured against the real face, 2026-11-13: DejaVu Sans Bold
#: at 110 % is 0.998 to 1.09 of Orbitron; 112 % keeps every name at or
#: above it). No face is fetched in a test: a title that fits in this one
#: fits in Orbitron.
ORBITRON_STANDIN = ("(function () { var st = document.createElement('style');"
                    " st.textContent = '@font-face { font-family: \"Orbitron\"; font-weight: 400 900;"
                    " src: local(\"DejaVu Sans Bold\"), local(\"DejaVuSans-Bold\"); size-adjust: 112%; }';"
                    " document.head.appendChild(st);"
                    " return document.fonts.load('600 15px Orbitron', 'A').then(function (f) { return f.length; }); })()")
#: Only words in the bar's title: letters, digits, spaces and punctuation.
TITLE_WORDS = re.compile(r"^[\w\s.,:;!?'’&()#/%+\-–—·…\"]+$")


def _menu(client):
    """Every page the menu links to, as the server renders it for him."""
    page = _get(client, POSITIONS)
    nav = page[page.index('<nav class="sidebar-nav"'):page.index("</nav>", page.index('<nav class="sidebar-nav"'))]
    return [h for h in re.findall(r'<a href="([^"]+)"[^>]*class="nav-link', nav) if h.startswith("/")]


def _bar_title(page):
    m = re.search(r'<span class="topbar-title">(.*?)</span>\s*(?:<script>.*?</script>\s*)?</div>\s*<form class="sv-cmd"', page, re.S)
    return m.group(1) if m else None


class BarTitleFilterTests(SimpleTestCase):
    """The bar's title is the page's name in words (F2: no glyph from a
    fallback face), its quieter words after the first " · " in their own
    span (F1: the frame lets them go before the name is ever cut)."""

    def render(self, raw):
        from django.template import Context, Template
        return Template("{% load sauron_tags %}{% filter sv_bar_title %}" + raw + "{% endfilter %}").render(Context({}))

    def test_the_glyph_goes_and_the_words_stay(self):
        self.assertEqual(self.render("◎ PORTFOLIO"), "PORTFOLIO")
        self.assertEqual(self.render("⚖ META-ALLOCATOR · LIVE"), 'META-ALLOCATOR<span class="sv-ttl-sub"> · LIVE</span>')
        self.assertEqual(self.render("⦿ OCULUS · every cycle, and whether it is turning"),
                         'OCULUS<span class="sv-ttl-sub"> · every cycle, and whether it is turning</span>')
        self.assertEqual(self.render("POSITIONS"), "POSITIONS")
        self.assertEqual(self.render("SYN100 — SYN100"), "SYN100 — SYN100")

    def test_a_title_that_wraps_its_words_keeps_its_markup(self):
        self.assertEqual(self.render('◎ <span class="pd-title-long">Long EURCAD · </span>Position #12'),
                         '<span class="pd-title-long">Long EURCAD · </span>Position #12')
        self.assertEqual(self.render('<span class="sv-plain">DEMO SHORT PROOFS · eToro\'s demo account</span>'),
                         '<span class="sv-plain">DEMO SHORT PROOFS · eToro\'s demo account</span>')


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameTitleFitTests(TestCase):
    """F1 and F2: on every page the menu links to, at 1280, 1440 and 1920,
    with REAL ARMED in the bar (its words are §10's), the page's name is
    whole on one line (scrollWidth <= clientWidth), no glyph opens it, and
    the top bar's right end stays in the window. Measured in a face at
    least as wide as Orbitron."""

    WIDTHS = ((1280, 800), (1440, 900), (1920, 1080))
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_titles")
        cls.titles = {}
        for href in _menu(client):
            cls.titles[href] = _bar_title(_get(client, href))
        pages = _pages(client, (POSITIONS,))
        b = _Browser(pages, "sv-frame-titles-")
        cls.got = {}
        try:
            for width, height in cls.WIDTHS:
                sid = b.tab(width, height)
                b.open(sid, POSITIONS)
                cls.standin = b.js(sid, ORBITRON_STANDIN)
                for href, html in sorted(cls.titles.items()):
                    cls.got[(href, width)] = json.loads(b.js(sid, (
                        "(function (h) { var t = document.querySelector('.topbar-title'); t.innerHTML = h;"
                        " if (window.SVFrameFit) SVFrameFit.top();"
                        " var top = document.querySelector('.topbar').getBoundingClientRect();"
                        " var right = document.querySelector('.topbar-right').getBoundingClientRect();"
                        " var armed = document.querySelector('.sv-armed-pill');"
                        " return JSON.stringify({ sw: t.scrollWidth, cw: t.clientWidth, lines: t.getClientRects().length,"
                        "   text: t.textContent.replace(/\\s+/g, ' ').trim(), right: right.right, top: top.right,"
                        "   armed: !!(armed && armed.getBoundingClientRect().width),"
                        "   step: document.querySelector('.topbar').getAttribute('data-sv-fit') }); })(%s)") % json.dumps(html)))
        finally:
            b.close()

    def test_every_menu_page_is_measured(self):
        self.assertGreaterEqual(len(self.titles), 55)
        self.assertEqual([h for h, t in self.titles.items() if t is None], [])
        self.assertGreater(self.standin, 0)

    def test_the_name_is_whole_on_one_line_at_every_width(self):
        cut = [(h, w, g["text"], g["sw"], g["cw"], g["step"]) for (h, w), g in sorted(self.got.items())
               if g["sw"] > g["cw"] + 0.5 or g["lines"] != 1]
        self.assertEqual(cut, [])

    def test_the_top_bar_stays_in_the_window_with_real_armed(self):
        out = [(h, w, g["right"], g["top"]) for (h, w), g in sorted(self.got.items()) if g["right"] > g["top"] - 15.5]
        self.assertEqual(out, [])
        self.assertTrue(all(g["armed"] for g in self.got.values()))

    def test_no_glyph_opens_a_title(self):
        bad = sorted({(h, g["text"]) for (h, w), g in self.got.items() if not TITLE_WORDS.match(g["text"])})
        self.assertEqual(bad, [])


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameBarUnderLoadTests(TestCase):
    """Contract F1 (§10) and F6, F16, F23: the bar as it is on a busy day.
    A real book whose P&L rests on a venue print 3 h old and covers part of
    the real rows, the bots STALLED, two seats in alarm (one real), a six-
    figure book. At 1280 and 1440: "· stale" and the "n/m" coverage are
    seen inside the real OPEN P&L; the seats' count is seen beside the
    standards; the alarm is an amber mark on a standard, never words across
    the bar; every cell holds one line and stops before the Eye. At 1920,
    where the bar has room, it takes cells back from "N more" (POSITIONS
    stays there: the Horde stands in its place)."""

    WIDTHS = ((1280, 800), (1440, 900), (1920, 1080))
    TAB = {"ok": True, "v": 1, "part": "tab", "seats": 5,
           "by_world": {"live": 3, "demo": 0, "paper": 2, "none": 0}, "alarms": 2, "alarm_real": True,
           "stragglers": 0, "lead": "live", "flag": None, "title_t": "The Horde", "aria_t": "The Horde",
           "attention_t": "2 seats need attention.",
           "sides": {"live": {"n": 3, "r_t": "+1.20R", "r_v": 1.2, "risk_pct_t": "1.75%", "limit_pct_t": "2.50%",
                              "risk_tone": "warn", "risk_why": "Synthetic"},
                     "demo": {"n": 0}, "paper": {"n": 2, "r_t": None, "r_v": None}}}
    BUSY = r"""(function () {
      var st = document.querySelector('[data-sv-cell="bots"] .hb-state');
      if (st) { st.className = 'hb-state hb-state--warn'; st.textContent = 'STALLED'; }
      var eq = document.querySelector('[data-sv-live="hb-real-equity"]');
      if (eq) eq.innerHTML = '<span>$110,453.61</span>';
      return 0; })()"""
    PROBE_MARKS = r"""(function () {
      function vis(el) {
        if (!el) return false;
        var cs = getComputedStyle(el), r = el.getBoundingClientRect();
        if (cs.display === 'none' || cs.visibility === 'hidden' || r.width === 0 || r.height === 0) return false;
        for (var p = el; p; p = p.parentElement) if (getComputedStyle(p).display === 'none') return false;
        return r.right <= innerWidth && r.left >= 0;
      }
      var pnl = document.querySelector('[data-sv-live="hb-real-pnl"]');
      var marks = Array.prototype.map.call(pnl.querySelectorAll('.sv-bar-mark'), function (m) {
        return { t: m.textContent.replace(/\s+/g, ' ').trim(), vis: vis(m) }; });
      var n = document.querySelector('[data-sv-cell="horde"] .sv-seats-n .sv-n');
      var alarm = document.querySelector('[data-sv-cell="horde"] .sv-seat.is-alarm');
      var bar = document.querySelector('.info-panel-wrap');
      var more = document.getElementById('svMoreBtn');
      var pop = document.getElementById('svMorePop');
      var released = Array.prototype.filter.call(document.querySelectorAll('.info-panel-bar > .ip-cat'), function (c) {
        return !c.hasAttribute('data-sv-cell'); }).map(function (c) { var l = c.querySelector('.ip-label'); return l ? l.textContent.trim() : '?'; });
      return JSON.stringify({ marks: marks, seatN: n ? { t: n.textContent.trim(), vis: vis(n) } : null,
        alarmMark: alarm ? { world: alarm.getAttribute('data-world'), fill: getComputedStyle(alarm.querySelector('.sv-alarm')).fill,
                             vis: getComputedStyle(alarm.querySelector('.sv-alarm')).display !== 'none' } : null,
        words: bar.innerText.replace(/\s+/g, ' '), label: document.getElementById('svHordeCell').getAttribute('aria-label'),
        step: bar.getAttribute('data-sv-bar-step'), more: more ? more.textContent.trim() : null, released: released,
        positionsWaits: !!(pop && pop.querySelector('#ipPositionsCount')) });
    })()"""

    @classmethod
    def setUpTestData(cls):
        from tests.test_headband_live_pnl import _real
        client = _book("frame_busy")
        user = get_user_model().objects.get(username="frame_busy")
        _real(user, symbol="ZZSTALEUSD", price="110", entry="100", stop="95", hours_ago=3)
        _real(user, symbol="ZZBLINDUSD", entry="50", stamp=False)
        before = ("window.fetch = function (u) { if (/part=tab/.test(String(u))) return Promise.resolve({ ok: true, status: 200,"
                  " redirected: false, headers: { get: function () { return 'application/json'; } },"
                  " json: function () { return Promise.resolve(%s); } }); return Promise.reject(new Error('offline')); };"
                  % json.dumps(cls.TAB))
        page = _get(client, POSITIONS)
        cls.page = page
        pages = {POSITIONS: _file_page(page, scripts=("sv-horde.js", "sv-frame.js"), before=before)}
        b = _Browser(pages, "sv-frame-busy-")
        cls.got = {}
        try:
            for width, height in cls.WIDTHS:
                sid = b.tab(width, height)
                b.open(sid, POSITIONS)
                b.js(sid, cls.BUSY)
                b.js(sid, "new Promise(function (r) { setTimeout(function () { r(0); }, 2200); })")
                b.js(sid, "window.SVFrameFit && SVFrameFit.bar(); 0")
                cls.got[width] = (json.loads(b.js(sid, PROBE)), json.loads(b.js(sid, cls.PROBE_MARKS)))
        finally:
            b.close()

    def test_the_fixture_is_stale_and_partial(self):
        span = self.page[self.page.index('data-sv-live="hb-real-pnl"'):]
        span = span[:span.index("</a>")]
        self.assertIn("&middot; stale", span)
        self.assertRegex(span, r"&middot; \d+/\d+")

    def test_stale_and_partial_are_seen_at_every_width(self):
        for width, (_g, m) in sorted(self.got.items()):
            with self.subTest(width=width):
                seen = [x["t"] for x in m["marks"] if x["vis"]]
                self.assertIn("· stale", seen)
                self.assertTrue(any(re.match(r"^· \d+/\d+$", t) for t in seen), m["marks"])

    def test_the_seats_count_is_always_said(self):
        for width, (_g, m) in sorted(self.got.items()):
            with self.subTest(width=width):
                self.assertTrue(m["seatN"] and m["seatN"]["vis"], m["seatN"])
                self.assertRegex(m["seatN"]["t"], r"^\d+$")

    def test_an_alarm_is_an_amber_mark_on_a_standard(self):
        warn = tuple(int(PALETTE["--sv-warn"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for width, (_g, m) in sorted(self.got.items()):
            with self.subTest(width=width):
                a = m["alarmMark"]
                self.assertTrue(a and a["vis"], m)
                self.assertEqual(a["world"], "live")
                self.assertTrue(_near([int(x) for x in re.findall(r"\d+", a["fill"])[:3]], warn), a["fill"])
                self.assertNotRegex(m["words"], r"(?i)\balarms?\b")
                self.assertIn("2 alarms", m["label"].lower())

    def test_every_cell_holds_one_line_before_the_eye(self):
        for width, (g, _m) in sorted(self.got.items()):
            with self.subTest(width=width):
                eye = g["eye"]
                for name, cell in g["cells"]:
                    if not cell or not cell["box"]["vis"]:
                        continue
                    self.assertEqual(cell["lines"], 1, "%s wraps: %r" % (name, cell["text"]))
                    self.assertLessEqual(cell["box"]["r"], eye["x"], name)

    def test_a_wide_bar_takes_cells_back_from_more(self):
        _g, m = self.got[1920]
        self.assertGreaterEqual(len(m["released"]), 1, m)
        self.assertNotIn("POSITIONS", m["released"])
        self.assertTrue(m["positionsWaits"])
        self.assertRegex(m["more"], r"^\d+ more$")
        self.assertLess(int(m["more"].split()[0]), 6)
        for width in (1280, 1440):
            self.assertEqual(self.got[width][1]["released"], [])


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameFocusAndKeysTests(TestCase):
    """F7, F12, F19, F22, contract F4 and the money dialogs:
      * after "/", the ring is the field's own (round the field and its "/"
        key), never the inner input's;
      * the lock with no PIN is the frame's ink, and focused it takes the
        kit's ring, never the Eye's wash;
      * one focus mark across the frame: the kit's 2 px Eye ring;
      * the first Tab stop is "Skip to the page", which lands in the page;
      * the money stops keep their order: REAL ARMED, the bell, the lock,
        the operator; the bar's CLOSE (data-sv-close-trade) is still
        reached through "N more", seen and on top;
      * "/" and "?" do nothing while a dialog holds the page."""

    RING = ".nav-fold, .sv-side-fold, .sv-dock-btn, #seEyeFab, #notifBell, #lockNowBtn, .nav-link, #svMoreBtn"

    @classmethod
    def setUpTestData(cls):
        client = _book("frame_focus")
        pages = _pages(client, (POSITIONS,))
        b = _Browser(pages, "sv-frame-focus-")
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
            # The first stop, and where it leads.
            b.js(sid, "document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); 0")
            key("Tab", "Tab", 9)
            cls.got["first"] = b.js(sid, "document.activeElement ? (document.activeElement.className || document.activeElement.id) : ''")
            key("Enter", "Enter", 13)
            cls.got["skipped"] = b.js(sid, "document.activeElement ? document.activeElement.id : ''")
            key("Tab", "Tab", 9)
            cls.got["next"] = b.js(sid, "!!(document.activeElement && document.activeElement.closest('.page-content'))")
            # "/" and its ring.
            b.js(sid, "document.activeElement && document.activeElement.blur(); 0")
            key("/", "Slash", 191)
            cls.got["slash"] = json.loads(b.js(sid, "(function () { var i = document.getElementById('svCmd'), f = i.closest('form');"
                                                    " var k = f.querySelector('.sv-kbd').getBoundingClientRect(), fb = f.getBoundingClientRect();"
                                                    " return JSON.stringify({ active: document.activeElement === i,"
                                                    "  input: getComputedStyle(i).boxShadow, form: getComputedStyle(f).boxShadow,"
                                                    "  keyInside: k.left >= fb.left && k.right <= fb.right }); })()"))
            key("Escape", "Escape", 27)
            # The lock with no PIN, at rest and focused.
            cls.got["lock"] = json.loads(b.js(sid, "(function () { var l = document.getElementById('lockNowBtn');"
                                                   " return JSON.stringify({ pin: l.getAttribute('data-has-pin'), color: getComputedStyle(l).color }); })()"))
            b.force(sid, "#lockNowBtn", ("focus-visible", "focus"))
            b.js(sid, "new Promise(function (r) { setTimeout(function () { r(0); }, 500); })")
            cls.got["lockFocus"] = b.js(sid, "getComputedStyle(document.getElementById('lockNowBtn')).backgroundColor")
            b.force(sid, "#lockNowBtn", ())
            # One ring: every focusable piece of the frame, forced.
            b.js(sid, "document.getElementById('mainSidebar').classList.add('force-hover'); 0")
            b.force(sid, cls.RING, ("focus-visible", "focus"))
            # Read once the controls' own transitions have run.
            b.js(sid, "new Promise(function (r) { setTimeout(function () { r(0); }, 500); })")
            cls.got["rings"] = json.loads(b.js(sid, "JSON.stringify(Array.prototype.map.call(document.querySelectorAll('%s'), function (e) {"
                                                    " var cs = getComputedStyle(e); return [e.id || e.className.split(' ')[0], cs.outlineStyle, cs.outlineWidth, cs.outlineColor]; }))"
                                                    % cls.RING))
            b.force(sid, cls.RING, ())
            # The money stops, in the order the browser walks them.
            cls.got["order"] = json.loads(b.js(sid, "(function () { var all = Array.prototype.filter.call(document.querySelectorAll("
                                                    " 'a[href], button, input, select, textarea, [tabindex]'), function (e) {"
                                                    " return e.tabIndex >= 0 && !e.disabled && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'; });"
                                                    " return JSON.stringify(['.sv-armed-pill', '#notifBell', '#lockNowBtn', '#userMenuTrigger', '.sv-skip'].map(function (s) {"
                                                    " return all.indexOf(document.querySelector(s)); })); })()"))
            # The bar's CLOSE, through "N more": the POSITIONS cell is seen
            # and on top once "N more" opens, and its list (the page's own
            # script portals it on hover, measured live in the PR) still
            # holds a CLOSE with data-sv-close-trade on every open row.
            b.js(sid, "document.getElementById('svMoreBtn').click(); 0")
            cls.got["close"] = json.loads(b.js(sid, "(function () { var c = document.getElementById('ipPositionsCount').closest('.ip-cat');"
                                                    " var r = c.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
                                                    " return JSON.stringify({ seen: r.width > 0 && r.height > 0 && !!h && (h === c || c.contains(h)),"
                                                    "  closes: Array.prototype.map.call(c.querySelectorAll('.ip-pos-close[data-sv-close-trade]'), function (x) {"
                                                    "   return [x.textContent.trim(), x.getAttribute('title'), x.getAttribute('type')]; }) }); })()"))
            b.js(sid, "document.body.click(); 0")
            # A dialog holds the page: "/" and "?" wait.
            b.js(sid, "(function () { var d = document.createElement('div'); d.className = 'sv-dialog is-open'; d.id = 'svProbeDialog';"
                      " d.innerHTML = '<button type=\"button\" id=\"svProbeBtn\">Confirm</button>'; document.body.appendChild(d);"
                      " document.getElementById('svProbeBtn').focus(); return 0; })()")
            key("/", "Slash", 191)
            key("?", "Slash", 191, 8)
            cls.got["held"] = json.loads(b.js(sid, "JSON.stringify({ active: document.activeElement ? document.activeElement.id : '',"
                                                   " keys: document.getElementById('kbdModalOverlay').classList.contains('open') })"))
        finally:
            b.close()

    def test_the_first_stop_skips_to_the_page(self):
        self.assertIn("sv-skip", self.got["first"])
        self.assertEqual(self.got["skipped"], "svPage")
        self.assertTrue(self.got["next"])

    def test_the_field_wears_its_own_ring(self):
        s = self.got["slash"]
        self.assertTrue(s["active"])
        self.assertEqual(s["input"], "none")
        self.assertIn("rgb(0, 232, 104)", s["form"])
        self.assertTrue(s["keyInside"])

    def test_the_lock_is_the_frame_s_ink_and_its_focus_no_wash(self):
        ink2 = "rgb(%d, %d, %d)" % tuple(int(PALETTE["--sv-ink-2"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        self.assertEqual(self.got["lock"]["pin"], "0")
        self.assertEqual(self.got["lock"]["color"], ink2)
        self.assertEqual(self.got["lockFocus"], "rgba(0, 0, 0, 0)")

    def test_one_focus_ring_across_the_frame(self):
        odd = [r for r in self.got["rings"] if (r[1], r[2], r[3]) != ("solid", "2px", "rgb(0, 232, 104)")]
        self.assertGreater(len(self.got["rings"]), 10)
        self.assertEqual(odd, [])

    def test_the_money_stops_keep_their_order(self):
        armed, bell, lock, user, skip = self.got["order"]
        self.assertEqual(skip, 0)
        self.assertGreater(armed, 0)
        self.assertLess(armed, bell)
        self.assertLess(bell, lock)
        self.assertLess(lock, user)

    def test_the_bar_s_close_is_reached_through_more(self):
        c = self.got["close"]
        self.assertTrue(c["seen"], c)
        self.assertGreaterEqual(len(c["closes"]), 1, c)
        for words, title, kind in c["closes"]:
            self.assertEqual((words, title, kind), ("Close", "Close this position", "button"))

    def test_a_dialog_keeps_the_keys(self):
        self.assertEqual(self.got["held"], {"active": "svProbeBtn", "keys": False})


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameLookDetailTests(TestCase):
    """F8 to F14, F17, F18, F20, F21, F24 and F15: the details the board
    draws and the build missed, read from the computed styles at 1440."""

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone
        from scraping.models import NewsArticle
        client = _book("frame_detail")
        NewsArticle.objects.create(title="Synthetic ministers meet on rates", source="Synthetic wire",
                                   url="https://example.test/frame/1", published_at=timezone.now())
        venue = (r"window.SVVenue = { now: function () { return 1700000000000; },"
                 r" get: function (s) { return { BTCUSD: { state: 'live' }, ETHUSD: { state: 'delayed', at: 1700000000000 - 3600000 },"
                 r" XAUUSD: { state: 'shut' }, EURUSD: { state: 'delayed', at: 1700000000000 - 60000 } }[s] || null; },"
                 r" stateAt: function (p) { return p.state; }, onPaint: function () {} };")
        page = _get(client, POSITIONS)
        cls.page = page
        # The one price's script stands at the foot of the page, after the
        # frame's (base.html): its stand-in is read after sv-frame.js too,
        # as the operator's browser reads them.
        framed = _file_page(page, scripts=("sv-frame.js",))
        i = framed.rindex("</body>")
        pages = {POSITIONS: framed[:i] + "<script>%s</script>" % venue + framed[i:]}
        b = _Browser(pages, "sv-frame-detail-")
        cls.got = {}
        try:
            sid = b.tab(1440, 900)
            b.open(sid, POSITIONS)
            cls.got["detail"] = json.loads(b.js(sid, r"""(function () {
              var q = function (s) { return document.querySelector(s); };
              var kbd = q('.sv-cmd .sv-kbd'), fold = q('.sidebar .nav-fold'), pill = q('#liveStatusPill .lsp-label');
              var row = q('.sidebar .nav-link:not(.active)'); var dot = document.createElement('span'); dot.className = 'nav-dot'; row.appendChild(dot);
              var lane = q('.sv-band .ticker-bar'), prices = q('.sv-band .data-headband');
              var dots = {}; Array.prototype.forEach.call(document.querySelectorAll('.sv-band .dh-item[data-symbol]'), function (it) {
                var d = it.querySelector('.dh-dot'); if (!d || it.getAttribute('aria-hidden')) return;
                var cs = getComputedStyle(d); dots[it.getAttribute('data-symbol')] = [d.getAttribute('data-sv-fresh'), cs.display, cs.backgroundColor, cs.borderTopWidth]; });
              return JSON.stringify({
                kbdShadow: getComputedStyle(kbd).boxShadow,
                foldPad: [getComputedStyle(fold).paddingLeft, getComputedStyle(fold).paddingRight],
                dot: getComputedStyle(dot).backgroundColor,
                pill: [getComputedStyle(pill).fontWeight, getComputedStyle(pill).textTransform],
                fades: [lane, prices].map(function (e) { var cs = getComputedStyle(e); return {
                  mask: cs.maskImage || cs.webkitMaskImage,
                  paint: [getComputedStyle(e, '::before').backgroundImage, getComputedStyle(e, '::after').backgroundImage] }; }),
                newsBadges: document.querySelectorAll('.ticker-item .t-badge.news').length,
                newsTimes: Array.prototype.map.call(document.querySelectorAll('.ticker-item[data-type="news"]:not([aria-hidden]) .t-time'), function (t) {
                  return [t.textContent.trim(), getComputedStyle(t).fontSize, getComputedStyle(t).color]; }),
                dots: dots,
                bubble: (function () { var g = q('.gollum-bubble'); return g ? getComputedStyle(g).maxWidth : null; })()
              }); })()"""))
            # The lanes hovered, their collapse buttons shown: the mask keeps
            # each button's own box whole.
            lanes = ".sv-band .ticker-bar, .sv-band .data-headband"
            b.force(sid, lanes, ("hover",))
            cls.got["hovered"] = json.loads(b.js(sid, r"""JSON.stringify(Array.prototype.map.call(
              document.querySelectorAll('.sv-band .ticker-bar, .sv-band .data-headband'), function (e) {
                var cs = getComputedStyle(e), r = e.getBoundingClientRect(), t = e.querySelector('.hb-collapse-btn').getBoundingClientRect();
                return { mask: cs.maskImage || cs.webkitMaskImage, size: cs.maskSize || cs.webkitMaskSize,
                         position: cs.maskPosition || cs.webkitMaskPosition, repeat: cs.maskRepeat || cs.webkitMaskRepeat,
                         button: [Math.round(r.right - t.right), Math.round(t.top - r.top), Math.round(t.width), Math.round(t.height)] }; }))"""))
            b.force(sid, lanes, ())
            # Folded to its icons: one short rule between groups, none under the brand.
            b.js(sid, "document.getElementById('mainSidebar').classList.add('mini'); 0")
            cls.got["mini"] = json.loads(b.js(sid, r"""(function () {
              var secs = Array.prototype.filter.call(document.querySelectorAll('.sidebar-nav .nav-section'), function (s) {
                return getComputedStyle(s).display !== 'none'; });
              var brand = document.querySelector('.sidebar-brand').getBoundingClientRect().bottom;
              return JSON.stringify({ first: secs.length ? secs[0].getBoundingClientRect().height : null,
                borders: secs.map(function (s) { return getComputedStyle(s).borderTopWidth; }),
                firstTop: secs.length ? secs[0].getBoundingClientRect().top - brand : null,
                bubble: (function () { var g = document.querySelector('.gollum-bubble'); return g ? getComputedStyle(g).display : null; })() }); })()"""))
            b.js(sid, "document.getElementById('mainSidebar').classList.remove('mini'); 0")
            # A lane shut: its chip names it, in its own slot.
            b.js(sid, "document.getElementById('tickerBar').classList.add('collapsed'); document.body.classList.add('hb-ticker-hidden'); 0")
            cls.got["chip"] = json.loads(b.js(sid, r"""(function () {
              var chip = document.querySelector('.hb-restore-tab.ticker'), lane = document.getElementById('dataHeadband');
              var c = chip.getBoundingClientRect(), l = lane.getBoundingClientRect();
              return JSON.stringify({ shown: getComputedStyle(chip).display !== 'none', text: chip.textContent.trim(),
                clear: c.left >= l.right - 0.5 }); })()"""))
            b.js(sid, "document.getElementById('tickerBar').classList.remove('collapsed'); document.body.classList.remove('hb-ticker-hidden'); 0")
            # The Eye's states.
            cls.got["eye"] = {}
            for st in ("live", "closed", "locked", "unknown"):
                cls.got["eye"][st] = json.loads(b.js(sid, (
                    "(function () { var e = document.querySelector('.sidebar-brand'); e.setAttribute('data-sv-eye', '%s');"
                    " var cs = function (s) { var n = e.querySelector(s); return n ? getComputedStyle(n).display : null; };"
                    " return JSON.stringify({ color: getComputedStyle(e.querySelector('.brand-eye')).color,"
                    "  lids: cs('.sv-brand-lids'), shut: cs('.sv-brand-shut'), almond: cs('.sv-brand-almond') }); })()") % st))
            # The light theme: the active row reads.
            b.js(sid, "document.body.classList.add('light-mode'); 0")
            cls.got["light"] = json.loads(b.js(sid, "(function () { var a = document.querySelector('.sidebar .nav-link.active');"
                                                    " var chain = []; for (var g = a; g; g = g.parentElement) chain.push(getComputedStyle(g).backgroundColor);"
                                                    " return JSON.stringify({ color: getComputedStyle(a).color, chain: chain }); })()"))
        finally:
            b.close()

    def test_the_key_caps_are_flat(self):
        self.assertEqual(self.got["detail"]["kbdShadow"], "none")

    def test_the_heads_take_the_board_s_padding(self):
        self.assertEqual(self.got["detail"]["foldPad"], ["18px", "14px"])

    def test_the_unseen_dot_is_one_colour(self):
        ink2 = "rgb(%d, %d, %d)" % tuple(int(PALETTE["--sv-ink-2"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        self.assertEqual(self.got["detail"]["dot"], ink2)

    def test_the_feed_pill_speaks_quietly(self):
        self.assertEqual(self.got["detail"]["pill"], ["400", "lowercase"])

    def test_each_lane_fades_at_both_ends(self):
        """Updated deliberately (the old-design guard, B0, merged from main):
        the fade is the board's own .lane mask, 12 px at each end, so the
        lane's items fade into the band's ground and nothing is painted over
        them; a painted fade on ::before and ::after was a gradient the
        guard counts on every page."""
        self.assertEqual(len(self.got["detail"]["fades"]), 2)
        for lane in self.got["detail"]["fades"]:
            with self.subTest(lane=lane):
                self.assertRegex(lane["mask"], r"^linear-gradient\(90deg, rgba\(0, 0, 0, 0\), rgb\(0, 0, 0\) 12px, "
                                               r"rgb\(0, 0, 0\) calc\(100% - 12px\), rgba\(0, 0, 0, 0\)\)$")
                self.assertEqual(lane["paint"], ["none", "none"])

    def test_a_shown_collapse_button_never_fades(self):
        """F8 kept: while a lane's collapse button shows, the mask's second
        layer is a solid box over the button's own (24 px, 4 px in from the
        lane's right and top), so the button never fades with the items."""
        self.assertEqual(len(self.got["hovered"]), 2)
        for lane in self.got["hovered"]:
            with self.subTest(lane=lane):
                # The button: 4 px in from the lane's right and top, 24 px.
                self.assertEqual(lane["button"], [4, 4, 24, 24])
                self.assertTrue(lane["mask"].endswith(", linear-gradient(rgb(0, 0, 0), rgb(0, 0, 0))"), lane["mask"])
                self.assertEqual(lane["size"], "100% 100%, 24px 24px")
                self.assertEqual(lane["position"], "0px 0px, calc(100% - 4px) 4px")
                self.assertEqual(lane["repeat"], "no-repeat, no-repeat")

    def test_a_headline_says_its_time_not_news(self):
        self.assertEqual(self.got["detail"]["newsBadges"], 0)
        times = self.got["detail"]["newsTimes"]
        self.assertGreaterEqual(len(times), 1)
        ink3 = "rgb(%d, %d, %d)" % tuple(int(PALETTE["--sv-ink-3"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for text, size, color in times:
            self.assertRegex(text, r"^\d\d:\d\d$")
            self.assertEqual((size, color), ("11px", ink3))

    def test_the_band_dot_is_the_price_s_freshness(self):
        dots = self.got["detail"]["dots"]
        # A flex item's display computes to block: shown, not "none".
        self.assertEqual(dots["BTCUSD"][0], "live")
        self.assertNotEqual(dots["BTCUSD"][1], "none")
        self.assertEqual(dots["ETHUSD"][0], "stale")
        self.assertEqual(dots["XAUUSD"][0], "closed")
        self.assertEqual(dots["XAUUSD"][3], "1px")
        self.assertEqual(dots["EURUSD"][0], "recent")
        # A symbol the one price holds no price for shows no dot at all.
        self.assertIsNone(dots["DXY"][0])
        self.assertEqual(dots["DXY"][1], "none")

    def test_the_folded_menu_draws_one_rule_and_none_under_the_brand(self):
        m = self.got["mini"]
        self.assertEqual(m["first"], 0)
        self.assertEqual(set(m["borders"]), {"0px"})
        self.assertEqual(m["bubble"], "none")

    def test_gollum_s_whisper_stays_in_the_menu_s_column(self):
        self.assertEqual(self.got["detail"]["bubble"], "%dpx" % (SIDE_W[1440] - 16))

    def test_a_shut_lane_s_chip_names_it_in_its_own_slot(self):
        c = self.got["chip"]
        self.assertTrue(c["shown"])
        self.assertIn("News", c["text"])
        self.assertTrue(c["clear"])

    def test_the_eye_s_states(self):
        e = self.got["eye"]
        ink3 = "rgb(%d, %d, %d)" % tuple(int(PALETTE["--sv-ink-3"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        self.assertEqual(e["unknown"]["color"], ink3)
        self.assertEqual(e["closed"]["lids"], "inline")
        self.assertEqual(e["locked"]["shut"], "inline")
        self.assertEqual(e["locked"]["almond"], "none")
        self.assertEqual(e["live"]["lids"], "none")
        self.assertEqual(e["live"]["shut"], "none")

    def test_the_active_row_reads_in_the_light_theme(self):
        """The row's own wash laid over the first opaque ground under it."""
        g = self.got["light"]
        layers = []
        for c in g["chain"]:
            v = [float(x) for x in re.findall(r"[\d.]+", c)]
            a = v[3] if len(v) > 3 else 1.0
            layers.append((v[:3], a))
            if a >= 0.999:
                break
        rgb = layers[-1][0] if layers and layers[-1][1] >= 0.999 else [255.0, 255.0, 255.0]
        for col, a in reversed(layers[:-1]):
            rgb = [col[i] * a + rgb[i] * (1 - a) for i in range(3)]
        ink = [float(x) for x in re.findall(r"[\d.]+", g["color"])[:3]]
        self.assertGreaterEqual(contrast(_hex(ink), _hex(rgb)), 4.5, g)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameLightTests(TestCase):
    """F3 and F4: the Eye's light never lifts the dark behind an amount
    (/positions/' eToro split line, Magic against Off: no lift), and where
    a page wears it, it falls from the Eye: brightest in the top gutter at
    the left, fading to nothing at the right, as on the board.

    Updated deliberately (stacked on B7, the desk v2 board approved
    2026-11-13: "amazing work, bravo, I need it fast!!"): B7 gives the
    split line its own ground, the popover the book card's equity opens
    (#pdEtoro, --sv-bg-2, in the top layer), so the frame no longer holds
    the light off /positions/ (its rule for a figure on the void said "until
    its page gives it a ground (B7)"). The line is read where it now is:
    the popover opened as a click opens it, its ground opaque, no light
    behind its amounts; the page wears the light."""

    #: The split line's ground: its nearest box (itself or up) that paints
    #: a background, whether that box is an open popover, and its alpha.
    GROUND = r"""(function () {
      var e = document.querySelector('[data-sv-live-key="pos.etoro.split"]');
      if (!e) return 'null';
      for (var n = e; n && n !== document.body; n = n.parentElement) {
        var cs = getComputedStyle(n), m = /rgba?\(([^)]+)\)/.exec(cs.backgroundColor), p = m ? m[1].split(',') : [];
        var a = m ? (p.length > 3 ? parseFloat(p[3]) : 1) : 0;
        if (a > 0 || (cs.backgroundImage && cs.backgroundImage !== 'none'))
          return JSON.stringify({ id: n.id, popover: n.hasAttribute('popover'), open: n.matches(':popover-open'),
                                  alpha: a, color: cs.backgroundColor });
      }
      return JSON.stringify(null);
    })()"""

    @classmethod
    def setUpTestData(cls):
        from PIL import ImageChops
        client = _book("frame_light")
        page = _get(client, POSITIONS)
        cls.split = 'data-sv-live-key="pos.etoro.split"' in page
        pages = {POSITIONS: _file_page(page, scripts=("sv-frame.js",))}
        b = _Browser(pages, "sv-frame-light-")
        cls.got = {}
        # The embers and the still grain (a texture across the whole void,
        # the same under every figure) are hidden: the light alone is read.
        still = ("(function () { var s = document.createElement('style'); s.textContent = '#particles-canvas { display: none !important; }"
                 " body::after { content: none !important; }"
                 " *, *::before, *::after { animation: none !important; transition: none !important; }'; document.head.appendChild(s);"
                 " return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(function () { r(0); }); }); }); })()")

        def lift(sid, clip):
            b.js(sid, "document.body.setAttribute('data-sv-ambience', 'magic'); 0")
            b.js(sid, "new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(function () { r(0); }); }); })")
            magic = b.shot(sid, clip)
            b.js(sid, "document.body.setAttribute('data-sv-ambience', 'off'); 0")
            b.js(sid, "new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(function () { r(0); }); }); })")
            off = b.shot(sid, clip)
            g = [max(0, a[1] - o[1]) for a, o in zip(magic.getdata(), off.getdata())]
            return max(g) if g else 0
        two_frames = ("new Promise(function (r) { requestAnimationFrame(function () {"
                      " requestAnimationFrame(function () { r(0); }); }); })")
        try:
            sid = b.tab(1440, 900)
            b.open(sid, POSITIONS)
            b.js(sid, still)
            # The line on its own ground (B7): the popover opened as the
            # book card's equity opens it (popovertarget="pdEtoro").
            b.js(sid, "(function () { var p = document.getElementById('pdEtoro');"
                      " if (p && !p.matches(':popover-open')) p.showPopover(); return 0; })()")
            b.js(sid, two_frames)
            cls.got["ground"] = json.loads(b.js(sid, cls.GROUND))
            r = json.loads(b.js(sid, "(function () { var e = document.querySelector('[data-sv-live-key=\"pos.etoro.split\"]');"
                                     " if (!e) return 'null'; var r = e.getBoundingClientRect();"
                                     " return JSON.stringify([Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]); })()"))
            # What is read is the dark behind the amounts, so their own ink
            # is taken out of both shots (#115's CI, 2026-11-14). Where the
            # machine draws sub-pixel text (the stock font rules, sub-pixel
            # RGB and slight hinting, as the CI has them: DejaVu with those
            # rules gives the CI's 19 here), the line's glyphs are drawn
            # with colour fringes on the plain ground under Off and in
            # grayscale over the void's composited layer under Magic: their
            # pixels differed by 19 levels of green, read as light, with no
            # light there. A glow or shadow of the text's own still shows
            # (a Magic-only glow on the line reads 28, the light reaching
            # it 6, against 0 as shipped).
            b.js(sid, "(function () { var e = document.querySelector('[data-sv-live-key=\"pos.etoro.split\"]'); if (!e) return 0;"
                      " [e].concat(Array.prototype.slice.call(e.querySelectorAll('*'))).forEach(function (n) {"
                      " n.style.setProperty('color', 'transparent', 'important'); }); return 0; })()")
            cls.got["split"] = lift(sid, r) if r and r[2] > 0 and r[3] > 0 else None
            # The page wears the light (nothing of its sits on the void):
            # the popover shut again, sampled in the top gutter, left to right.
            b.js(sid, "(function () { var p = document.getElementById('pdEtoro');"
                      " if (p && p.matches(':popover-open')) p.hidePopover(); return 0; })()")
            b.js(sid, two_frames)
            top = json.loads(b.js(sid, "JSON.stringify([document.querySelector('.sv-band').getBoundingClientRect().bottom,"
                                       " document.querySelector('.page-content').getBoundingClientRect().left])"))
            y = int(top[0]) + 4
            cls.got["gutter"] = [lift(sid, (x, y, 8, 6)) for x in (int(top[1]) + 24, 600, 1000, 1340)]
        finally:
            b.close()

    def test_the_fixture_prints_the_split_line_on_its_own_ground(self):
        self.assertTrue(self.split)
        g = self.got["ground"]
        self.assertIsNotNone(g)
        self.assertEqual((g["id"], g["popover"], g["open"], g["alpha"]), ("pdEtoro", True, True, 1), g)

    def test_no_light_behind_the_split_line_s_amounts(self):
        self.assertIsNotNone(self.got["split"])
        self.assertLessEqual(self.got["split"], 1)

    def test_the_light_falls_from_the_eye(self):
        g = self.got["gutter"]
        self.assertGreaterEqual(g[0], 5, g)
        self.assertEqual(g, sorted(g, reverse=True))
        self.assertLessEqual(g[-1], 1, g)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FrameEmbersOffTheFiguresTests(TestCase):
    """F3, its embers half: /positions/ opted into the embers, and its eToro
    split line ("At that read: opened by Sauron … · P&L …") prints amounts
    straight on the void, where the embers drift. The magic's first rule
    holds there too (never on a figure; Twist2: "aucune lueur ni reflet
    derrière un montant"): on and within 8 px of every figure on the void,
    no free ember or ash is drawn (the field's own rule for a card: gone
    within 12 px, whole again at 24 px), and no gutter channel comes within
    12 px of one, while the field still draws on the page.

    Updated deliberately (stacked on B7, the desk v2 board approved
    2026-11-13: "amazing work, bravo, I need it fast!!"): B7 gives the line
    its own ground (the popover the book card opens), so the page prints no
    figure on the void of its own any more, which is held here too: every
    figure found on the void is the fixture's line. The fixture prints the
    line as #115 measured it, straight on the void at the head of the page
    where the embers drift whole, in the words the book renders, so
    sv-embers.js's rule for figures on the void is still read on this
    page."""

    #: Every figure on the void (a text with a digit and no ground of any
    #: kind under it, up to <body>), the alpha a free ember of alpha 1 is
    #: drawn at on and around each, and how near a channel comes to one.
    PROBE = r"""(function () {
      var s = window.__svEmberStats, boxes = [];
      __sv.figureNodes().forEach(function (f) {
        for (var n = f[1]; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
          var cs = getComputedStyle(n), c = __sv.rgba(cs.backgroundColor);
          if ((cs.backgroundImage && cs.backgroundImage !== 'none') || (c && c.a > 0)) return;
        }
        var rg = document.createRange(); rg.selectNodeContents(f[0]);
        var r = rg.getBoundingClientRect();
        if (r.width && r.height && r.bottom > 0 && r.top < innerHeight)
          boxes.push([r.left, r.top, r.right, r.bottom, f[2].slice(0, 32),
                      !!f[1].closest('[data-sv-live-key="pos.etoro.split"]')]);
      });
      var lit = [];
      boxes.forEach(function (b) {
        var cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
        [[cx, cy], [b[0] + 1, cy], [b[2] - 1, cy], [b[0] - 6, b[1] - 6], [b[2] + 6, b[3] + 6],
         [cx, b[1] - 8], [cx, b[3] + 8]].forEach(function (p) {
          var a = s.groundAt(p[0], p[1], 1);
          if (a > 0) lit.push([b[4], Math.round(p[0]), Math.round(p[1]), Math.round(a * 100) / 100]);
        });
      });
      var near = [];
      s.channels().forEach(function (c) {
        boxes.forEach(function (b) {
          var dx = Math.max(b[0] - c[2], c[0] - b[2], 0), dy = Math.max(b[1] - c[3], c[1] - b[3], 0);
          if (Math.sqrt(dx * dx + dy * dy) < 12) near.push([b[4], c.map(Math.round)]);
        });
      });
      return JSON.stringify({ maps: s.maps, onVoid: boxes.length, split: boxes.filter(function (b) { return b[5]; }).length,
                              texts: boxes.map(function (b) { return b[4]; }), lit: lit, near: near });
    })()"""

    @classmethod
    def setUpTestData(cls):
        from tests.test_magic_layer import EMBER_COUNTER, EMBER_WINDOW, PROBES
        client = _book("frame_embers")
        page = _get(client, POSITIONS)
        cls.split = 'data-sv-live-key="pos.etoro.split"' in page
        # The line as #115 measured it: on no ground, where the embers drift
        # whole (32 px clear of the band and the first card, beyond the
        # field's 24 px), at the head of the page, in the words of the split
        # line B7 now prints in its popover.
        words = re.search(r'data-sv-live-key="pos\.etoro\.split">(.*?)</p>', page, re.S)
        if words:
            at = page.index(">", page.index('<div class="page-content')) + 1
            page = (page[:at] + '<p class="sv-void-line" style="margin: 32px 0;"'
                    ' data-sv-live-key="pos.etoro.split">%s</p>' % words.group(1) + page[at:])
        pages = {POSITIONS: _file_page(page, scripts=("sv-embers.js",), before=EMBER_COUNTER)}
        b = _Browser(pages, "sv-frame-embers-")
        try:
            sid = b.tab(1440, 900)
            b.open(sid, POSITIONS, PROBES)
            b.js(sid, "(function () { return new Promise(function (r) { var n = 0, t = setInterval(function () {"
                      " if ((window.__svEmberStats && __svEmberStats.maps) || ++n > 100) { clearInterval(t); r(0); } }, 50); }); })()")
            b.js(sid, "new Promise(function (r) { setTimeout(function () { r(0); }, 900); })")
            cls.got = json.loads(b.js(sid, cls.PROBE))
            cls.window = b.js(sid, EMBER_WINDOW + "(1000)")
        finally:
            b.close()

    def test_the_fixture_prints_figures_on_the_void(self):
        self.assertTrue(self.split)
        self.assertGreaterEqual(self.got["maps"], 1, self.got)
        self.assertGreaterEqual(self.got["split"], 1, self.got)
        # The page's own figures all sit on a ground (B7): the fixture's
        # line is the only one on the void.
        self.assertEqual(self.got["onVoid"], self.got["split"], self.got["texts"])

    def test_no_ember_on_or_near_a_figure_on_the_void(self):
        self.assertEqual(self.got["lit"], [], self.got["texts"])

    def test_no_channel_runs_by_a_figure_on_the_void(self):
        self.assertEqual(self.got["near"], [])

    def test_the_field_still_draws_on_the_page(self):
        self.assertGreater(self.window["embers"], 0, self.window)
        self.assertGreater(self.window["frames"], 0, self.window)


class RealGroupWordsTests(SimpleTestCase):
    """Contract F2: the REAL chip and its group claim only what each cell
    is. PORTFOLIO, OPEN P&L and MARGIN are eToro's own figures for the real
    book; AT STOPS is the entry gate's measure of it; DRAWDOWN is this
    book's daily snapshots (the per-user portfolio, no bot trades), so it
    stands outside the group and its title says so."""

    def group(self):
        base = read(BASE)
        i = base.index('<div class="sv-sgrp"')
        return base[i:base.index('data-sv-cell="bots"', i)], base

    def test_the_group_holds_the_real_book_s_cells_and_not_the_drawdown(self):
        grp, _base = self.group()
        head, _rest = grp.split("</div>\n                {% comment %}\n                DRAWDOWN", 1)
        for cell in ("portfolio", "pnl", "stops", "margin"):
            self.assertIn('data-sv-cell="%s"' % cell, head)
        self.assertNotIn('data-sv-cell="drawdown"', head)

    def test_the_words_claim_only_what_each_cell_is(self):
        grp, base = self.group()
        label = re.search(r'<div class="sv-sgrp" role="group" aria-label="([^"]+)"', base).group(1)
        self.assertNotIn("eToro's own figures", label)
        self.assertIn("as the entry gate measures", label)
        chip = re.search(r'class="sv-world sv-world--live sv-sb-real" title="([^"]+)"', base).group(1)
        self.assertIn("AT STOPS as the entry gate measures", chip)
        self.assertIn("not the real book at eToro", re.search(
            r'data-sv-cell="drawdown" class="ip-cat ip-cat-link" title="([^"]+)"', base).group(1))


class RealPnlWordsTests(TestCase):
    """Contract F1, ported from tests.test_headband_live_pnl to the figure
    the operator sees now (hb-real-pnl, the bar's OPEN P&L): a real book
    marked in part says "· 1/2", one resting on a venue print hours old says
    "· stale", each in a mark the bar never lets go (.sv-bar-mark), its
    sentence as the mark's title."""

    def setUp(self):
        from tests.test_headband_live_pnl import _components, _config, _tick, _user
        self.user = _user("frame_words")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def words(self):
        from tests.test_headband_live_pnl import _page, _span, _words
        body = _page(self.client)
        return _words(body, "hb-real-pnl"), _span(body, "hb-real-pnl")

    def test_a_partly_marked_real_book_says_so_in_the_bar(self):
        from tests.test_headband_live_pnl import _quote as _q, _real
        _real(self.user, price="110", entry="100", stop="95")
        _q("XAUUSD", "2668", asset_class="commodity")
        _real(self.user, symbol="XAUUSD", entry="2650", stamp=False)
        words, span = self.words()
        self.assertIn("· 1/2", words)
        self.assertIn('<span class="sv-bar-mark sv-unknown" title="Across 1 of 2 real-money positions', span)

    def test_a_stale_venue_print_is_said_in_the_bar(self):
        from tests.test_headband_live_pnl import _real
        _real(self.user, price="110", entry="100", stop="95", hours_ago=3)
        words, span = self.words()
        self.assertTrue(words.endswith("· stale"), words)
        self.assertIn('<span class="sv-bar-mark sv-unknown" title="The real-money position rests on the venue', span)
