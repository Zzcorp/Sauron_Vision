"""THE DOORS: opening and closing made easy (desk v2, 2026-11-15).

The operator, the morning after the desk v2 frame merged:

    "non the way the tabs and headbands open and close is hideous restore
    the old system only, of opening and closing icons, their old sizes too
    for the horde tab too and the council and the activity... you
    understand? Its truly horrible, hideous, bad work for sure"

then, having used it:

    "okay i start to understand how it works, make it better and easier to
    use please"

and, about the look:

    "while youre upgrading the style more, please make sure its also
    visually attractive/ visually easy to understand, with the use of
    different colors, bold, italic... etc... elegant icons... etc"
    "its already the case a bit but upgrade even more"

The desk v2 frame and look stay. What comes back is what the old doors did
better, drawn in the kit (openclose/spec.md, the mock openclose/mock/):

  * EVERY DOOR SHOWS AT REST, with its word and a sprite icon, at the old
    size: the band's PRICES and NEWS switches (88 x 31, at the band's right
    end), the dock's 28 px tabs (SIGNALS 28 x 112, COUNCIL and ACTIVITY at
    the old 28 x 112, ASK SAURON 28 x 136, 16 px apart), THE HORDE in the
    bar at the old tab's 28 px, the menu's FOLD THE MENU row at its foot,
    Gollum's face and the Eye in the bar. Nothing at opacity 0.
  * ONE DOOR, ONE PLACE: one click opens, the same click in the same place
    closes; the door never moves, hides or tucks.
  * ONE RIGHT-COLUMN PANEL AT A TIME (Signals, Council, Activity, Ask): the
    others shut and are stored shut.
  * THE HORDE'S SHEET RISES FROM THE BAR, between the menu and the column,
    and shut it lets the page's clicks through.
  * ESC CLOSES THE LAST PANEL OPENED, one per press, the focus back on its
    door; never a lane or the menu; nothing while a money dialog, the PIN or
    the lock holds the page (held()).
  * EVERY DOOR IS A NATIVE BUTTON in the Tab order; the money controls keep
    their Tab sequence.
  * CHOICES FOLLOW HIM to the next page.
  * COLOUR THAT MEANS SOMETHING: the Council in --sv-ai (violet, the
    models), the Activity in --sv-cat-1 (blue), Signals and Ask lit by the
    Eye's line (the Eye never paints a door at rest), the Horde its
    standards; QUIET when shut (bg-2, line-3, ink-2, 600), LIT when open
    (ink-1, 700, the accent at 18 % on bg-1 for the Council and the
    Activity, a 2 px inset line on the panel's side, the chevron turned).
  * WORDS READ: 4.5:1 for words and hints, 3:1 for icons, dark and light.
  * ONE ICON FAMILY: the sprite, stroke 1.5; no glyph left in a door or a
    close.
  * MOTION SHORT AND CALM: 140 ms, none under reduced motion or Ambience
    Off.

Display only: no order, no broker, no model, no network (every fetch is
held). Every row is synthetic (the frame tests' _book). The measured classes
skip without a Chromium.

Run with:  python manage.py test tests.test_doors_measured
"""
import json
import re
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from tests.test_close_advice import CHROME, _quote, _trade
from tests.test_design_tokens import PALETTE, contrast
from tests.test_magic_layer import _Browser, _file_page
from tests.test_shell_frame_measured import EQUITY, POSITIONS, PORTFOLIO, USED
from tests.test_ui_s0_fixes import _get

#: The two desk widths the spec draws (1440 is 1425 wide with the page's
#: scrollbar, 1280 is 1265).
WIDTHS = ((1440, 900), (1280, 800))
#: The doors, by the hooks the frame keeps.
SEL = {
    "prices": '.sv-band-doors [data-collapse="data"]',
    "news": '.sv-band-doors [data-collapse="ticker"]',
    "signals": '.sv-dock [data-sv-dock="signals"]',
    "council": '.sv-dock [data-sv-dock="council"]',
    "activity": '.sv-dock [data-sv-dock="activity"]',
    "ask": '.sv-dock [data-sv-dock="ask"]',
    "horde": "#svHordeCell",
    "fold": ".sv-fold-row",
    "gollum": "#gollumFab",
    "eye": "#seEyeFab",
}
#: The word each door says (Gollum's face and the Eye name themselves in
#: their tooltips).
WORDS = {"prices": "PRICES", "news": "NEWS", "signals": "SIGNALS", "council": "COUNCIL",
         "activity": "ACTIVITY", "ask": "ASK SAURON", "horde": "THE HORDE", "fold": "FOLD THE MENU"}
DOCK = ("signals", "council", "activity", "ask")
#: The panel each door opens, and how the page says it is open.
OPEN = {
    "signals": "!!document.querySelector('#signalsRail.open')",
    "council": "!!document.querySelector('#svCouncilBand.open')",
    "activity": "!!document.querySelector('#svActivity.open')",
    "ask": "!!document.querySelector('#seChatPanel.open')",
    "horde": "!!document.querySelector('#svHorde.open')",
    "gollum": "!document.getElementById('gollumDialog').hidden",
    "eye": "!!document.querySelector('#seChatPanel.open')",
}
#: The light palette (sv-tokens.css, body.light-mode).
LIGHT = {"--sv-bg-1": "#ffffff", "--sv-bg-2": "#e8ece8", "--sv-bg-3": "#f5f8f5", "--sv-line-3": "#a0c0a0",
         "--sv-ink-1": "#1a2a1a", "--sv-ink-2": "#4a6a4a", "--sv-ink-3": "#8aaa8a", "--sv-eye": "#00994d",
         "--sv-ai": "#8840d0", "--sv-cat-1": "#1f6fb2", "--sv-up": "#00994d", "--sv-down": "#e83030"}
#: The panels' scripts, as the page loads them (sv-frame.js last), and the
#: page's own inline scripts the doors need: the lanes' setter and memory,
#: the menu's memory, Ask Sauron's panel (each found by a line it holds).
SCRIPTS = ("sv-gollum.js", "sv-activity.js", "sv-horde.js", "sv-council-band.js", "sv-frame.js")
INLINE = ("// Headband collapse / restore", "function toggleSidebar()", "var fab = document.getElementById('seEyeFab');")
#: Nothing leaves the page: every read is held, unanswered (the panels say
#: they are loading).
HOLD = "window.fetch = function () { return new Promise(function () {}); };"
#: The §10 money controls (the old-design guard's list).
MONEY = (".tk-side, .tk-long, .tk-short, [data-sv-close-trade], #svCloseAll, .sr-pop-btn, .sr-gone-btn-ticket, "
         ".btn-buy, .btn-sell, .btn-stop, .sz-confirm, .sz-dialog .sv-dialog-btn, input[type=\"password\"], "
         "form[action*=\"toggle\"] button, form[action*=\"component\"] button, .sv-armed-pill, .ip-pos-close")


def _rgb(hexs):
    h = hexs.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(c)) for c in rgb[:3])


def _parse(css):
    """[r, g, b, a] of a computed colour, or None."""
    m = re.match(r"rgba?\(([^)]+)\)", css or "")
    if m:
        p = [float(x) for x in re.split(r"[ ,/]+", m.group(1).strip()) if x]
        return p[:3] + [p[3] if len(p) > 3 else 1.0]
    m = re.match(r"color\(srgb ([\d.e-]+) ([\d.e-]+) ([\d.e-]+)(?: / ([\d.]+))?\)", css or "")
    if m:
        return [float(m.group(i)) * 255 for i in (1, 2, 3)] + [float(m.group(4)) if m.group(4) else 1.0]
    return None


def _near(css, hexs, tol=2):
    c = _parse(css)
    return bool(c) and all(abs(a - b) <= tol for a, b in zip(c[:3], _rgb(hexs)))


def _mix(accent, ground, share):
    a, g = _rgb(accent), _rgb(ground)
    return _hex([a[i] * share + g[i] * (1 - share) for i in range(3)])


def _book(name):
    """The frame tests' book (tests.test_shell_frame_measured._book) with
    the spec's five seats: three real at eToro, one at eToro's demo, one
    paper (its board's Horde: THE HORDE, five standards, "5 seats")."""
    from tests.test_signal_acted_and_sizing import _signal
    from tests.test_used_is_etoros import _cfg, _etoro, _row
    user = get_user_model().objects.create_user(name, password="x", is_staff=True, is_superuser=True)
    _signal(_quote("BTCUSD", 60600).instrument, direction="bullish", rule="frame_up")
    _signal(_quote("ETHUSD", 2600).instrument, direction="bearish", entry=2600, stop=2700,
            target=2400, rule="frame_down")
    _quote("XAUUSD", 2648.12, asset_class="commodity")
    for sym, px in (("AAPL", 227.06), ("MSFT", 410.20), ("NVDA", 140.10)):
        _quote(sym, px, asset_class="stock")
    _etoro(user, demo=False, used=USED, cash="6051.51", pnl="76.26", total=EQUITY,
           balance="10377.35", age_s=40)
    live = _cfg(user, cls="stock", name="doors_live", mode="live")
    for sym, qty, px in (("AAPL", 4, 228.10), ("MSFT", 2, 405.00), ("NVDA", 5, 138.00)):
        _row(live, sym, qty, px)
    _row(live, "AAPL", 1, 226.00, env="paper")
    _trade(user)
    client = Client()
    client.force_login(user)
    return client


def _plain(name):
    """A reader who is not staff (the Council and the Activity are staff's
    panels, so their doors are not drawn for him): ASK SAURON stands where
    the Council does (§2.2)."""
    user = get_user_model().objects.create_user(name, password="x")
    client = Client()
    client.force_login(user)
    return client


#: The page of a reader who is not staff, by its key among the pages.
NONSTAFF = "nonstaff"


def _pages(client, urls):
    """The pages as files Chromium opens on its own, with the panels'
    scripts and the inline ones the doors need, in the order the browser
    runs them: the inline ones while the page is read, then the deferred."""
    out = {}
    for url in urls:
        page = _get(client, url)
        inline = [m.group(1) for m in re.finditer(r"<script>(.*?)</script>", page, re.S)
                  if any(k in m.group(1) for k in INLINE)]
        framed = _file_page(page, scripts=SCRIPTS, before=HOLD)
        at = framed.index('<script src="')
        tags = "".join("<script>%s</script>" % s.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
                       for s in inline)
        out[url] = framed[:at] + tags + framed[at:]
    return out


#: Every door and the frame around it, as computed.
PROBE = r"""
window.__d = (function () {
  var SEL = __SEL__;
  function q(s) { return document.querySelector(s); }
  function r1(v) { return Math.round(v * 10) / 10; }
  function box(e) { var r = e.getBoundingClientRect(); return { x: r1(r.left), y: r1(r.top), w: r1(r.width), h: r1(r.height), r: r1(r.right), b: r1(r.bottom) }; }
  function rgba(s) { var m = /rgba?\(([^)]+)\)/.exec(s || ''); if (!m) return null; var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
  function opacity(e) { var o = 1; for (var n = e; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return Math.round(o * 100) / 100; }
  function shown(e) {
    if (!e) return false;
    var cs = getComputedStyle(e), r = e.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility === 'visible' && r.width > 0 && r.height > 0;
  }
  function onTop(e) {
    var r = e.getBoundingClientRect();
    var t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!t && (t === e || e.contains(t));
  }
  function ground(e) {
    for (var n = e; n && n.nodeType === 1; n = n.parentElement) {
      var c = rgba(getComputedStyle(n).backgroundColor);
      if (c && c[3] >= 0.99) return 'rgb(' + c.slice(0, 3).join(', ') + ')';
    }
    return getComputedStyle(document.body).backgroundColor;
  }
  function icons(e) {
    return Array.prototype.map.call(e.querySelectorAll('svg'), function (s) {
      var cs = getComputedStyle(s), u = s.querySelector('use'), r = s.getBoundingClientRect();
      return { cls: String(s.getAttribute('class') || ''), use: u ? u.getAttribute('href') : null, w: r1(r.width), h: r1(r.height),
               color: cs.color, stroke: cs.stroke, sw: cs.strokeWidth, transform: cs.transform, transition: cs.transitionDuration,
               shown: cs.display !== 'none' && cs.visibility === 'visible' && r.width > 0, inTip: !!s.closest('.sv-door-tip') };
    });
  }
  /* The text a door draws outside its words, its counts and its tip: a
     glyph standing for an icon. */
  function glyphs(e) {
    var out = '', w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) {
      var n = w.currentNode, p = n.parentElement;
      if (!p || p.closest('.sv-door-tip, .sv-door-word, .sv-door-n, .sv-dock-n, .ip-label, .sv-seats-wrap, .gollum-count, .sv-sr, svg')) continue;
      if (getComputedStyle(p).display === 'none') continue;
      out += n.nodeValue;
    }
    return out.replace(/\s+/g, '');
  }
  function door(name) {
    var e = q(SEL[name]);
    if (!e) return null;
    var cs = getComputedStyle(e), word = e.querySelector('.sv-door-word, .ip-label');
    var wcs = word ? getComputedStyle(word) : cs;
    var n = e.querySelector('.sv-door-n'), tip = e.querySelector('.sv-door-tip-hint');
    var hcs = tip ? getComputedStyle(tip) : null, tipBox = e.querySelector('.sv-door-tip');
    return {
      tag: e.tagName, type: e.getAttribute('type'), tabIndex: e.tabIndex, disabled: !!e.disabled,
      box: box(e), shown: shown(e), opacity: opacity(e), onTop: shown(e) && onTop(e),
      words: word && shown(word) ? word.innerText.replace(/\s+/g, ' ').trim() : '',
      color: wcs.color, weight: wcs.fontWeight, size: wcs.fontSize, face: wcs.fontFamily.split(',')[0].replace(/["']/g, '').trim(),
      tt: wcs.textTransform, wordGround: ground(word || e),
      bg: cs.backgroundColor, ground: ground(e), borderW: cs.borderTopWidth, borderC: cs.borderTopColor,
      borderL: cs.borderLeftColor, outline: cs.outlineStyle + ' ' + cs.outlineColor, shadow: cs.boxShadow,
      transition: cs.transitionDuration, transform: cs.transform,
      expanded: e.getAttribute('aria-expanded'), pressed: e.getAttribute('aria-pressed'),
      title: e.getAttribute('title'), label: e.getAttribute('aria-label'),
      icons: icons(e), glyphs: glyphs(e),
      badge: n ? { shown: shown(n), border: getComputedStyle(n).borderTopColor, bg: getComputedStyle(n).backgroundColor,
                   color: getComputedStyle(n).color, face: getComputedStyle(n).fontFamily.split(',')[0].replace(/["']/g, '').trim() } : null,
      hint: tip ? { color: hcs.color, style: hcs.fontStyle, size: hcs.fontSize, ground: ground(tipBox),
                    face: hcs.fontFamily.split(',')[0].replace(/["']/g, '').trim() } : null
    };
  }
  function all() { var o = {}; Object.keys(SEL).forEach(function (k) { o[k] = door(k); }); return o; }
  function center(name) { var e = q(SEL[name]); if (!e) return null; var r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }
  function frame() {
    var bar = q('.info-panel-wrap'), hp = q('#svHordePanel'), dock = q('.sv-dock'), dirs = q('.sv-dock-dirs');
    var store = {};
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); store[k] = localStorage.getItem(k); } } catch (e) {}
    return { vw: document.documentElement.clientWidth, vh: innerHeight, bar: bar ? box(bar) : null,
             dock: dock ? box(dock) : null, hordePanel: hp ? box(hp) : null, store: store,
             dirs: dirs && shown(dirs) ? box(dirs) : null,
             dirsInk: dirs ? Array.prototype.map.call(dirs.querySelectorAll('.up, .down'), function (s) {
               var g = s.querySelector('.sv-dir-g');
               return { side: s.className, count: getComputedStyle(s).color, glyph: g ? getComputedStyle(g).color : null }; }) : [],
             side: box(q('.sidebar')), mini: !!q('.sidebar.mini'),
             barStep: bar ? bar.getAttribute('data-sv-bar-step') : null,
             hordeText: q('#svHordeCell') ? q('#svHordeCell').innerText.replace(/\s+/g, ' ').trim() : null,
             seats: Array.prototype.map.call(document.querySelectorAll('#svHordeCell .sv-seat'), function (x) { return x.getAttribute('data-world'); }),
             news: { collapsed: !!q('#tickerBar.collapsed') }, prices: { collapsed: !!q('#dataHeadband.collapsed') },
             active: document.activeElement ? (document.activeElement.id || document.activeElement.className || document.activeElement.tagName) : null };
  }
  function isOpen() { return __OPEN__; }
  function activeIs(name) { var e = q(SEL[name]); return !!e && document.activeElement === e; }
  function closes() {
    var out = {};
    [['council_x', '#svCouncilBandClose'], ['council_widen', '#svCouncilBandWiden'], ['activity_x', '#svActivityClose'],
     ['horde_x', '#svHordeClose'], ['gollum_x', '#gollumDialog [data-gollum-close]'], ['ask_close', '#seChatClose']].forEach(function (p) {
      var e = q(p[1]);
      if (!e) { out[p[0]] = null; return; }
      out[p[0]] = { box: box(e), shown: shown(e), icons: icons(e), glyphs: glyphs(e), text: (e.innerText || '').trim(),
                    color: getComputedStyle(e).color, borderC: getComputedStyle(e).borderTopColor };
    });
    return out;
  }
  function railHeads() {
    return Array.prototype.map.call(document.querySelectorAll('.signals-rail .rail-head'), function (h) {
      var b = h.querySelector('button.rh-fold, button.rail-head') || (h.tagName === 'BUTTON' ? h : null);
      var chev = h.querySelector('.rh-chev');
      return { button: !!b, expanded: b ? b.getAttribute('aria-expanded') : null, controls: b ? b.getAttribute('aria-controls') : null,
               tab: b ? b.tabIndex : null, chev: chev ? { tag: chev.tagName.toLowerCase(), box: box(chev), use: chev.querySelector('use') ? chev.querySelector('use').getAttribute('href') : null,
                                                        transform: getComputedStyle(chev).transform } : null,
               glyphs: glyphs(h).replace(/\d+/g, '') };
    });
  }
  /* A door's tip (§2.8): shown or not, where, and what it says. */
  function tip(name) {
    var e = q(SEL[name]);
    if (!e) return null;
    var t = e.querySelector('.sv-door-tip');
    if (!t) return { door: box(e), tip: null, shown: false };
    var cs = getComputedStyle(t), nm = t.querySelector('.sv-door-tip-name'), k = t.querySelector('kbd');
    var h = t.querySelector('.sv-door-tip-hint'), hcs = h ? getComputedStyle(h) : null;
    return { door: box(e), tip: box(t), shown: cs.visibility === 'visible' && parseFloat(cs.opacity) > 0.99,
             name: nm ? nm.textContent.replace(/\s+/g, ' ').trim() : '', nameWeight: nm ? getComputedStyle(nm).fontWeight : null,
             nameTT: nm ? getComputedStyle(nm).textTransform : null, key: k ? k.textContent.trim() : null,
             hint: h ? h.textContent.replace(/\s+/g, ' ').trim() : '', hintStyle: hcs ? hcs.fontStyle : null,
             hintSize: hcs ? hcs.fontSize : null, focusVisible: e.matches(':focus-visible'),
             oldTab: Array.prototype.map.call(document.querySelectorAll('#svHordeTab .hd-tab-seats, #svHordeTab .hd-tab-r, #svHordeTab .hd-tab-risk'),
               function (s) { return s.hidden ? '' : s.textContent.replace(/\s+/g, ' ').trim(); }).filter(Boolean) };
  }
  return { door: door, all: all, center: center, frame: frame, isOpen: isOpen, activeIs: activeIs, closes: closes, railHeads: railHeads, tip: tip };
})();
0
""".replace("__SEL__", json.dumps(SEL)).replace(
    "__OPEN__", "{" + ", ".join("%s: %s" % (k, v) for k, v in OPEN.items()) + "}")

#: The frame's tab stops in order, each with the zone it sits in.
TAB_ORDER = r"""(function (money) {
  var all = Array.prototype.filter.call(document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]'), function (e) {
    if (e.tabIndex < 0 || e.disabled || e.closest('[inert]')) return false;
    for (var n = e; n && n.nodeType === 1; n = n.parentElement) { if (getComputedStyle(n).display === 'none') return false; }
    return getComputedStyle(e).visibility !== 'hidden' && e.getClientRects().length > 0;
  });
  function zone(e) {
    return e.closest('#mainSidebar') ? 'menu' : e.closest('.topbar') ? 'topbar' : e.closest('.sv-band-doors') ? 'doors'
      : e.closest('#svBand') ? 'band' : e.closest('#infoPanelWrap') ? 'bar' : e.closest('.page-content') ? 'page'
      : e.closest('.sv-dock') ? 'dock' : e.id === 'gollumFab' ? 'gollum' : e.id === 'seEyeFab' ? 'eye' : e.classList.contains('sv-skip') ? 'skip' : 'other';
  }
  var zones = [];
  all.forEach(function (e) { var z = zone(e); if (!zones.length || zones[zones.length - 1] !== z) zones.push(z); });
  var m = all.filter(function (e) { return e.matches(money); }).map(function (e) {
    return [e.tagName.toLowerCase(), (e.innerText || e.value || '').replace(/\s+/g, ' ').trim(),
            e.getAttribute('data-sv-close-trade') ? 'close-trade' : (e.id || String(e.className).split(' ')[0])]; });
  var idx = function (s) { var e = document.querySelector(s); return all.indexOf(e); };
  var heads = all.filter(function (e) { return e.matches('.signals-rail .rail-head button.rh-fold, .signals-rail button.rail-head'); }).length;
  return JSON.stringify({ zones: zones, money: m, n: all.length, heads: heads,
    fold: idx('.sv-fold-row'), lastMenu: (function () { var k = -1; all.forEach(function (e, i) { if (e.closest('#mainSidebar')) k = i; }); return k; })(),
    prices: idx('.sv-band-doors [data-collapse="data"]'), news: idx('.sv-band-doors [data-collapse="ticker"]'),
    horde: idx('#svHordeCell'), more: idx('#svMoreBtn'), gollum: idx('#gollumFab'), eye: idx('#seEyeFab'),
    dock: ['signals', 'council', 'activity', 'ask'].map(function (n) { return idx('.sv-dock [data-sv-dock="' + n + '"]'); }),
    doors: ['.sv-band-doors [data-collapse="data"]', '.sv-band-doors [data-collapse="ticker"]', '.sv-dock [data-sv-dock="signals"]',
            '.sv-dock [data-sv-dock="council"]', '.sv-dock [data-sv-dock="activity"]', '.sv-dock [data-sv-dock="ask"]',
            '#svHordeCell', '.sv-fold-row', '#gollumFab', '#seEyeFab'].map(function (s) { var e = document.querySelector(s);
              return e ? [s, e.tagName, e.tabIndex] : [s, null, null]; }) });
})(%s)""" % json.dumps(MONEY)


def _wait(b, sid, ms):
    b.js(sid, "new Promise(function (r) { setTimeout(function () { r(0); }, %d); })" % ms)


def _mouse(b, sid, x, y, kind="mouseMoved", button="none", clicks=0):
    b.chrome.call("Input.dispatchMouseEvent", {"type": kind, "x": float(x), "y": float(y), "button": button,
                                               "clickCount": clicks}, session=sid)


#: Where the pointer rests between clicks: the page's empty top gutter.
AWAY = (700, 84)


def _click(b, sid, name, ms=350):
    """A real click at the door's centre (the pointer moved, pressed,
    released), then the pointer away, and the door's motion run out."""
    c = json.loads(b.js(sid, "JSON.stringify(__d.center(%s))" % json.dumps(name)))
    if not c:
        return False
    _mouse(b, sid, c[0], c[1])
    _mouse(b, sid, c[0], c[1], "mousePressed", "left", 1)
    _mouse(b, sid, c[0], c[1], "mouseReleased", "left", 1)
    _mouse(b, sid, *AWAY)
    _wait(b, sid, ms)
    return True


def _key(b, sid, key, code, vk, mods=0):
    for kind in ("rawKeyDown", "keyUp"):
        b.chrome.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                 "nativeVirtualKeyCode": vk, "modifiers": mods}, session=sid)


def _esc(b, sid):
    _key(b, sid, "Escape", "Escape", 27)
    _wait(b, sid, 300)


def _fresh(b, sid, url):
    """The page with nothing remembered, read by the probe."""
    b.open(sid, url, "try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}")
    b.open(sid, url)
    _mouse(b, sid, *AWAY)
    b.js(sid, PROBE)
    _wait(b, sid, 300)


def _all(b, sid):
    return json.loads(b.js(sid, "JSON.stringify(__d.all())"))


def _state(b, sid):
    return json.loads(b.js(sid, "JSON.stringify(__d.isOpen())"))


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DoorsMeasuredTests(TestCase):
    """The doors at 1440 x 900 and 1280 x 800, dark and light, at rest,
    hovered, clicked open and shut, closed by Esc, walked by Tab and carried
    to the next page."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        client = _book("doors")
        pages = _pages(client, (POSITIONS, PORTFOLIO))
        pages[NONSTAFF] = _pages(_plain("doors_plain"), (POSITIONS,))[POSITIONS]
        b = _Browser(pages, "sv-doors-")
        cls.rest, cls.hover, cls.lit, cls.away, cls.clicks, cls.cols = {}, {}, {}, {}, {}, {}
        cls.horde, cls.esc, cls.tabs, cls.follow, cls.closes, cls.heads, cls.motion = {}, {}, {}, {}, {}, {}, {}
        cls.tips, cls.plain = {}, {}
        try:
            for width, height in WIDTHS:
                sid = b.tab(width, height)
                for theme in ("dark", "light"):
                    key = (width, theme)
                    _fresh(b, sid, POSITIONS)
                    if theme == "light":
                        b.js(sid, "document.body.classList.add('light-mode'); 0")
                        _wait(b, sid, 250)
                    cls.rest[key] = dict(_all(b, sid), frame=json.loads(b.js(sid, "JSON.stringify(__d.frame())")))
                    # Hovered (the forced pseudo-state the guard's census uses).
                    hov = {}
                    for name in ("prices", "signals", "council", "activity", "ask", "horde", "fold"):
                        if b.force(sid, SEL[name], ("hover",)):
                            _wait(b, sid, 200)
                            hov[name] = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                            b.force(sid, SEL[name], ())
                    cls.hover[key] = hov
                    # Lit: each door clicked open, read with the pointer away.
                    lit = {}
                    for name in ("signals", "council", "activity", "ask", "horde", "gollum"):
                        _click(b, sid, name, 450)
                        lit[name] = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        if name == "ask":
                            lit["eye"] = json.loads(b.js(sid, "JSON.stringify(__d.door('eye'))"))
                        if theme == "dark":
                            cls.closes[(width, name)] = json.loads(b.js(sid, "JSON.stringify(__d.closes())"))
                        if name == "signals":
                            cls.heads[key] = json.loads(b.js(sid, "JSON.stringify(__d.railHeads())"))
                        _click(b, sid, name, 450)
                    cls.lit[key] = lit
                    # Away: a lane put away from its own door.
                    _click(b, sid, "news")
                    cls.away[key] = json.loads(b.js(sid, "JSON.stringify(__d.door('news'))"))
                    _click(b, sid, "news")
                    if theme == "light":
                        continue
                    # ── one click opens, one click closes, in place ──
                    _fresh(b, sid, POSITIONS)
                    got = {}
                    for name in ("signals", "council", "activity", "ask", "horde", "gollum", "eye"):
                        before = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        _click(b, sid, name, 450)
                        opened = _state(b, sid).get(name)
                        mid = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        _click(b, sid, name, 450)
                        shut = not _state(b, sid).get(name)
                        after = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        got[name] = {"before": before, "open": mid, "after": after, "opened": opened, "shut": shut}
                    for name in ("prices", "news"):
                        before = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        _click(b, sid, name)
                        mid = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        fr = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                        _click(b, sid, name)
                        after = json.loads(b.js(sid, "JSON.stringify(__d.door(%s))" % json.dumps(name)))
                        fr2 = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                        got[name] = {"before": before, "open": mid, "after": after,
                                     "opened": fr[name]["collapsed"], "shut": not fr2[name]["collapsed"]}
                    before = json.loads(b.js(sid, "JSON.stringify(__d.door('fold'))"))
                    _click(b, sid, "fold")
                    mid = json.loads(b.js(sid, "JSON.stringify(__d.door('fold'))"))
                    fold_frame = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                    _click(b, sid, "fold")
                    after = json.loads(b.js(sid, "JSON.stringify(__d.door('fold'))"))
                    got["fold"] = {"before": before, "open": mid, "after": after, "opened": fold_frame["mini"],
                                   "shut": not json.loads(b.js(sid, "JSON.stringify(__d.frame())"))["mini"]}
                    cls.clicks[width] = got
                    # ── one right-column panel at a time ──
                    _fresh(b, sid, POSITIONS)
                    cols = []
                    for first, then in (("signals", "council"), ("council", "activity"), ("activity", "ask"), ("ask", "signals")):
                        _click(b, sid, first, 450)
                        _click(b, sid, then, 450)
                        st = _state(b, sid)
                        fr = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                        cols.append({"first": first, "then": then, "state": st, "store": fr["store"]})
                        _click(b, sid, then, 450)
                    cls.cols[width] = cols
                    # ── the Horde rises from the bar ──
                    _fresh(b, sid, POSITIONS)
                    shut_hit = b.js(sid, "(function () { var t = document.elementFromPoint(600, innerHeight - 46);"
                                         " return t ? !!t.closest('#svHorde') : null; })()")
                    _click(b, sid, "horde", 600)
                    alone = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                    _click(b, sid, "signals", 600)
                    beside = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                    _click(b, sid, "signals", 450)
                    _click(b, sid, "horde", 600)
                    after_hit = b.js(sid, "(function () { var t = document.elementFromPoint(600, innerHeight - 46);"
                                          " return t ? !!t.closest('#svHorde') : null; })()")
                    cls.horde[width] = {"shut_hit": shut_hit, "alone": alone, "beside": beside, "after_hit": after_hit}
                    # ── Esc closes the last panel opened ──
                    _fresh(b, sid, POSITIONS)
                    esc = {}
                    _click(b, sid, "council", 450)
                    _esc(b, sid)
                    esc["one"] = {"state": _state(b, sid), "focus": b.js(sid, "__d.activeIs('council')")}
                    _click(b, sid, "horde", 600)
                    _click(b, sid, "council", 450)
                    _esc(b, sid)
                    esc["two_first"] = {"state": _state(b, sid), "focus": b.js(sid, "__d.activeIs('council')")}
                    _esc(b, sid)
                    esc["two_second"] = {"state": _state(b, sid), "focus": b.js(sid, "__d.activeIs('horde')")}
                    # Lanes and the menu: Esc never touches them.
                    _click(b, sid, "news")
                    _click(b, sid, "fold")
                    _click(b, sid, "activity", 450)
                    _esc(b, sid)
                    _esc(b, sid)
                    fr = json.loads(b.js(sid, "JSON.stringify(__d.frame())"))
                    esc["lanes_menu"] = {"state": _state(b, sid), "news_away": fr["news"]["collapsed"], "mini": fr["mini"]}
                    _click(b, sid, "fold")
                    _click(b, sid, "news")
                    # A money dialog holds the page: Esc is the dialog's.
                    _click(b, sid, "horde", 600)
                    _click(b, sid, "signals", 450)
                    b.js(sid, "(function () { var d = document.createElement('div'); d.className = 'sv-dialog is-open'; d.id = 'svProbeDialog';"
                              " d.innerHTML = '<button type=\"button\" id=\"svProbeBtn\">Confirm</button>'; document.body.appendChild(d);"
                              " document.getElementById('svProbeBtn').focus(); return 0; })()")
                    _esc(b, sid)
                    esc["held"] = {"state": _state(b, sid), "focus": b.js(sid, "document.activeElement ? document.activeElement.id : ''")}
                    b.js(sid, "document.getElementById('svProbeDialog').remove(); 0")
                    cls.esc[width] = esc
                    # ── Tab: native buttons, the frame's order, the money's ──
                    _fresh(b, sid, POSITIONS)
                    cls.tabs[width] = {"rest": json.loads(b.js(sid, TAB_ORDER))}
                    _click(b, sid, "signals", 450)
                    cls.tabs[width]["rail"] = json.loads(b.js(sid, TAB_ORDER))
                    cls.tabs[width]["heads"] = json.loads(b.js(sid, "JSON.stringify(__d.railHeads())"))
                    _click(b, sid, "signals", 450)
                    # ── the tips: a name, a key, one italic line ──
                    _fresh(b, sid, POSITIONS)
                    # The Horde's tab painted as sv-horde.js paints it from
                    # its board (every read is held here): the spec's
                    # invented figures.
                    b.js(sid, "(function () { var t = document.getElementById('svHordeTab'); if (!t) return 0;"
                              " var r = t.querySelector('.hd-tab-r'), k = t.querySelector('.hd-tab-risk');"
                              " if (r) { r.textContent = '+1.60R'; r.hidden = false; }"
                              " if (k) { k.textContent = 'risk 1.8% of 2.5%'; k.hidden = false; } return 0; })()")
                    tips = {}
                    for name in ("signals", "council", "activity", "ask", "horde"):
                        c = json.loads(b.js(sid, "JSON.stringify(__d.center(%s))" % json.dumps(name)))
                        if c:
                            _mouse(b, sid, c[0], c[1])
                            _wait(b, sid, 750)
                        tips[name] = json.loads(b.js(sid, "JSON.stringify(__d.tip(%s))" % json.dumps(name)))
                        _mouse(b, sid, *AWAY)
                        _wait(b, sid, 250)
                    # The census's forced pseudo-states never draw one.
                    for name, states in (("council", ("hover",)), ("horde", ("focus-visible",))):
                        b.force(sid, SEL[name], states)
                        _wait(b, sid, 750)
                        tips["forced_" + name] = json.loads(b.js(sid, "JSON.stringify(__d.tip(%s))" % json.dumps(name)))
                        b.force(sid, SEL[name], ())
                    # The keyboard: Tab onto a door shows its tip at once.
                    b.js(sid, "document.querySelector(%s).focus(); 0" % json.dumps(SEL["signals"]))
                    _key(b, sid, "Tab", "Tab", 9)
                    _wait(b, sid, 300)
                    tips["focus"] = json.loads(b.js(sid, "JSON.stringify(__d.tip('council'))"))
                    cls.tips[width] = tips
                    # ── a reader who is not staff: ASK SAURON where the Council stands ──
                    _fresh(b, sid, NONSTAFF)
                    cls.plain[width] = {"ask": json.loads(b.js(sid, "JSON.stringify(__d.door('ask'))")),
                                        "council": json.loads(b.js(sid, "JSON.stringify(__d.door('council'))")),
                                        "frame": json.loads(b.js(sid, "JSON.stringify(__d.frame())"))}
                    # ── choices follow to the next page ──
                    _fresh(b, sid, POSITIONS)
                    _click(b, sid, "news")
                    _click(b, sid, "council", 450)
                    here = _all(b, sid)
                    b.open(sid, PORTFOLIO)
                    b.js(sid, PROBE)
                    _wait(b, sid, 300)
                    there = _all(b, sid)
                    cls.follow[width] = {"here": here, "there": there,
                                         "frame": json.loads(b.js(sid, "JSON.stringify(__d.frame())")),
                                         "state": _state(b, sid)}
            # ── motion: 140 ms, none under reduced motion or Ambience Off ──
            sid = b.tab(1440, 900)
            _fresh(b, sid, POSITIONS)
            cls.motion["magic"] = _all(b, sid)
            b.js(sid, "document.body.setAttribute('data-sv-ambience', 'off'); 0")
            cls.motion["off"] = _all(b, sid)
            sid = b.tab(1440, 900, reduced=True)
            _fresh(b, sid, POSITIONS)
            cls.motion["reduced"] = _all(b, sid)
        finally:
            b.close()

    # ── helpers ──────────────────────────────────────────────────────────
    def themes(self):
        for (width, theme), got in sorted(self.rest.items()):
            yield width, theme, got

    def pal(self, theme, token):
        return (LIGHT if theme == "light" else {k: v for k, v in PALETTE.items()}).get(token) or PALETTE[token]

    # ══════════════════════════════════════════════════════════════════════
    def test_every_door_shows_at_rest(self):
        """Every door is there at rest, at full strength, on top, and says
        its word (Gollum's face and the Eye name themselves)."""
        for width, theme, got in self.themes():
            for name in SEL:
                with self.subTest(width=width, theme=theme, door=name):
                    d = got[name]
                    self.assertIsNotNone(d, "%s is not in the frame" % name)
                    self.assertTrue(d["shown"], d)
                    self.assertEqual(d["opacity"], 1, d)
                    self.assertTrue(d["onTop"], "%s is under something at its centre" % name)
                    if name in WORDS:
                        self.assertEqual(d["words"], WORDS[name])

    def test_old_sizes_and_places(self):
        """The spec's boxes (§2), within a pixel: the band's switches at its
        right end, the dock's tabs at the old 28 px, THE HORDE at the old
        tab's 28 px, the fold row at the menu's foot, Gollum and the Eye in
        the bar; the old 18 px arrow (12 put away), the 12 px chevrons in the
        dock, 14 in the bar and the rail's heads, 24 px closes with 16 px
        icons."""
        for width, theme, got in self.themes():
            fr = got["frame"]
            vw, vh = fr["vw"], fr["vh"]
            boxes = {
                "prices": (vw - 176, 44, 88, 31), "news": (vw - 88, 44, 88, 31),
                "signals": (vw - 33.5, 88, 28, 112), "council": (vw - 33.5, 248, 28, 112),
                "activity": (vw - 33.5, 376, 28, 112), "ask": (vw - 33.5, 504, 28, 136),
                "fold": (0, vh - 64, 231, 32), "gollum": (0, vh - 32, 46, 32), "eye": (vw - 35, vh - 29, 26, 26),
            }
            for name, want in boxes.items():
                with self.subTest(width=width, theme=theme, door=name):
                    d = got[name]
                    self.assertIsNotNone(d)
                    b = d["box"]
                    for k, v in zip(("x", "y", "w", "h"), want):
                        self.assertAlmostEqual(b[k], v, delta=1, msg="%s %s: %r" % (name, k, b))
            with self.subTest(width=width, theme=theme, door="dirs"):
                # SIGNALS' long and short split, under its tab: ▲3 ▼2 at
                # y 204-232, centred on the dock's tabs.
                dirs = fr["dirs"]
                self.assertIsNotNone(dirs)
                self.assertAlmostEqual(dirs["y"], 204, delta=1, msg=dirs)
                self.assertAlmostEqual(dirs["b"], 232, delta=1, msg=dirs)
                self.assertAlmostEqual(dirs["x"] + dirs["w"] / 2, vw - 19.5, delta=1, msg=dirs)
            with self.subTest(width=width, theme=theme, door="horde"):
                h = got["horde"]
                self.assertIsNotNone(h)
                self.assertAlmostEqual(h["box"]["h"], 28, delta=1, msg=h["box"])
                self.assertGreaterEqual(h["box"]["y"], vh - 32, h["box"])
                self.assertAlmostEqual(h["box"]["w"], {1440: 230.8, 1280: 199.9}[width], delta=1,
                                       msg=(h["box"], fr.get("barStep"), fr.get("hordeText"), fr.get("seats")))
                chev = [i for i in h["icons"] if "sv-door-chev" in i["cls"]]
                self.assertEqual([(i["w"], i["h"]) for i in chev], [(14, 14)], h["icons"])
            for name in DOCK:
                with self.subTest(width=width, theme=theme, icons=name):
                    self.assertIsNotNone(got[name], name)
                    ics = {("ico" if "sv-door-ico" in i["cls"] else "chev"): (i["w"], i["h"])
                           for i in got[name]["icons"] if not i["inTip"] and ("sv-door-ico" in i["cls"] or "sv-door-chev" in i["cls"])}
                    self.assertEqual(ics, {"ico": (16, 16), "chev": (12, 12)})
            for name in ("prices", "news"):
                with self.subTest(width=width, theme=theme, arrow=name):
                    self.assertIsNotNone(got[name], name)
                    arrows = [(i["w"], i["h"]) for i in got[name]["icons"] if "sv-door-arrow" in i["cls"]]
                    self.assertEqual(arrows, [(18, 18)])
            with self.subTest(width=width, theme=theme, arrow="away"):
                away = self.away[(width, theme)]
                self.assertIsNotNone(away)
                arrows = [(i["w"], i["h"]) for i in away["icons"] if "sv-door-arrow" in i["cls"]]
                self.assertEqual(arrows, [(12, 12)])
        for (width, name), closes in sorted(self.closes.items()):
            for key in {"council": ("council_x", "council_widen"), "activity": ("activity_x",),
                        "horde": ("horde_x",)}.get(name, ()):
                with self.subTest(width=width, close=key):
                    c = closes[key]
                    self.assertIsNotNone(c)
                    self.assertEqual((c["box"]["w"], c["box"]["h"]), (24, 24), c)
                    self.assertEqual([(i["w"], i["h"]) for i in c["icons"]], [(16, 16)], c)
        for key, heads in sorted(self.heads.items()):
            for h in heads:
                with self.subTest(at=key, head=h):
                    self.assertIsNotNone(h["chev"])
                    self.assertEqual((h["chev"]["box"]["w"], h["chev"]["box"]["h"]), (14, 14))
        # A reader who is not staff has no Council or Activity door: ASK
        # SAURON stands at y 248, where the Council's does.
        self.assertEqual(sorted(self.plain), [1280, 1440])
        for width, p in sorted(self.plain.items()):
            with self.subTest(width=width, reader="not staff"):
                self.assertIsNone(p["council"])
                self.assertIsNotNone(p["ask"])
                for k, v in zip(("x", "y", "w", "h"), (p["frame"]["vw"] - 33.5, 248, 28, 136)):
                    self.assertAlmostEqual(p["ask"]["box"][k], v, delta=1, msg=(k, p["ask"]["box"]))

    def test_tips_name_key_and_one_italic_line(self):
        """§2.8: after 400 ms of hover a door's tip says its name in bold
        capitals and its key, then one line in italics; to the left of a
        dock's tab, centred on it, and above THE HORDE, whose line is the
        old tab's figures word for word. The keyboard shows it at once; the
        census's forced :hover and :focus-visible never draw one."""
        names = {"signals": "Signals", "council": "Council", "activity": "Activity", "ask": "Ask Sauron",
                 "horde": "The Horde"}
        keys = {"council": "c", "ask": "Ctrl K", "horde": "h"}
        self.assertEqual(sorted(self.tips), [1280, 1440])
        for width, tips in sorted(self.tips.items()):
            for name in names:
                with self.subTest(width=width, door=name):
                    t = tips[name]
                    self.assertIsNotNone(t)
                    self.assertIsNotNone(t["tip"], "%s has no tip" % name)
                    self.assertTrue(t["shown"], t)
                    self.assertTrue(t["name"].startswith(names[name]), t)
                    self.assertEqual((t["nameWeight"], t["nameTT"]), ("700", "uppercase"), t)
                    self.assertEqual(t["key"], keys.get(name), t)
                    self.assertTrue(t["hint"], t)
                    self.assertEqual((t["hintStyle"], t["hintSize"]), ("italic", "12px"), t)
                    tip, door = t["tip"], t["door"]
                    if name == "horde":
                        self.assertLessEqual(tip["b"], door["y"] - 6, t)
                        self.assertEqual(t["hint"], " · ".join(t["oldTab"]), t)
                        self.assertEqual(t["hint"], "5 seats · +1.60R · risk 1.8% of 2.5%", t)
                    else:
                        self.assertLessEqual(tip["r"], door["x"] - 8, t)
                        self.assertAlmostEqual(tip["y"] + tip["h"] / 2, door["y"] + door["h"] / 2, delta=1, msg=t)
            for name in ("council", "horde"):
                with self.subTest(width=width, forced=name):
                    f = tips["forced_" + name]
                    self.assertIsNotNone(f)
                    self.assertIsNotNone(f["tip"], f)
                    self.assertFalse(f["shown"], f)
            with self.subTest(width=width, keyboard=True):
                f = tips["focus"]
                self.assertTrue(f["focusVisible"], f)
                self.assertTrue(f["shown"], f)

    def test_one_click_opens_one_click_closes_in_place(self):
        """A real click opens the panel; the door stays where it was, on
        top; a second click in the same place closes it. A lane's switch is
        the same door both ways and says so (aria-pressed)."""
        for width, got in sorted(self.clicks.items()):
            for name, g in sorted(got.items()):
                with self.subTest(width=width, door=name):
                    self.assertIsNotNone(g["before"], name)
                    self.assertTrue(g["opened"], "%s did not open" % name)
                    self.assertTrue(g["shut"], "%s did not close on the second click" % name)
                    self.assertIsNotNone(g["open"], "%s left its place" % name)
                    self.assertTrue(g["open"]["shown"] and g["open"]["onTop"], "%s is gone while open" % name)
                    if name == "fold":
                        # The row keeps its line and its icon's place; folded it is 55 px.
                        self.assertEqual((g["open"]["box"]["x"], g["open"]["box"]["y"], g["open"]["box"]["h"]),
                                         (g["before"]["box"]["x"], g["before"]["box"]["y"], g["before"]["box"]["h"]))
                        self.assertAlmostEqual(g["open"]["box"]["w"], 55, delta=1)
                        ico = [i for i in g["open"]["icons"] if i["shown"]]
                        ico0 = [i for i in g["before"]["icons"] if i["shown"]]
                        self.assertEqual(len(ico), 1)
                        self.assertEqual(len(ico0), 1)
                        continue
                    for k in ("x", "y", "w", "h"):
                        self.assertAlmostEqual(g["open"]["box"][k], g["before"]["box"][k], delta=0.5,
                                               msg="%s moved: %r -> %r" % (name, g["before"]["box"], g["open"]["box"]))
                        self.assertAlmostEqual(g["after"]["box"][k], g["before"]["box"][k], delta=0.5)
                    if name in ("prices", "news"):
                        self.assertEqual((g["before"]["pressed"], g["open"]["pressed"], g["after"]["pressed"]),
                                         ("true", "false", "true"))
                        self.assertEqual(g["before"]["title"], "Hide %s" % {"prices": "prices", "news": "news"}[name])
                        self.assertEqual(g["open"]["title"], "Show %s" % {"prices": "prices", "news": "news"}[name])
                    else:
                        self.assertEqual((g["before"]["expanded"], g["open"]["expanded"], g["after"]["expanded"]),
                                         ("false", "true", "false"))

    def test_one_column(self):
        """Signals, Council, Activity and Ask share the right column: the
        one opened shuts the other, which is stored shut."""
        keys = {"signals": ("sauron_signals_rail", "closed"), "council": ("sauron_council_band_open", "closed"),
                "activity": ("sauron_activity_open", None)}
        for width, cols in sorted(self.cols.items()):
            for c in cols:
                with self.subTest(width=width, first=c["first"], then=c["then"]):
                    self.assertTrue(c["state"][c["then"]], c)
                    self.assertFalse(c["state"][c["first"]], "%s stayed open under %s" % (c["first"], c["then"]))
                    if c["first"] in keys:
                        k, v = keys[c["first"]]
                        self.assertIn(k, c["store"])
                        if v:
                            self.assertEqual(c["store"][k], v)
                        else:
                            self.assertIn(c["store"][k], ("0", "closed", "false"))

    def test_horde_rises_from_the_bar(self):
        """The sheet stands on the bar's top edge, from the menu's edge to
        the dock or the open column; shut, nothing of it lies over the
        page."""
        for width, h in sorted(self.horde.items()):
            with self.subTest(width=width):
                for k in ("alone", "beside"):
                    fr = h[k]
                    p, bar = fr["hordePanel"], fr["bar"]
                    self.assertIsNotNone(p)
                    self.assertAlmostEqual(p["b"], bar["y"], delta=1, msg=(k, p, bar))
                    self.assertAlmostEqual(p["x"], fr["side"]["r"], delta=1, msg=(k, p))
                    self.assertGreater(p["h"], 120, (k, p))
                right = {"alone": h["alone"]["vw"] - 40, "beside": h["beside"]["vw"] - 40 - {1440: 340, 1280: 300}[width]}
                for k, want in right.items():
                    self.assertAlmostEqual(h[k]["hordePanel"]["r"], want, delta=1, msg=(k, h[k]["hordePanel"]))
                self.assertIs(h["shut_hit"], False)
                self.assertIs(h["after_hit"], False)

    def test_esc_last_opened_focus_back(self):
        """Esc after a click closes what the click opened and puts the
        focus back on its door; two open, the last goes first; the lanes
        and the menu are never Esc's; a money dialog keeps its Esc."""
        for width, esc in sorted(self.esc.items()):
            with self.subTest(width=width):
                self.assertFalse(esc["one"]["state"]["council"], esc)
                self.assertTrue(esc["one"]["focus"], esc)
                self.assertFalse(esc["two_first"]["state"]["council"], esc)
                self.assertTrue(esc["two_first"]["state"]["horde"], esc)
                self.assertTrue(esc["two_first"]["focus"], esc)
                self.assertFalse(esc["two_second"]["state"]["horde"], esc)
                self.assertTrue(esc["two_second"]["focus"], esc)
                self.assertFalse(esc["lanes_menu"]["state"]["activity"], esc)
                self.assertTrue(esc["lanes_menu"]["news_away"], esc)
                self.assertTrue(esc["lanes_menu"]["mini"], esc)
                self.assertTrue(esc["held"]["state"]["horde"] and esc["held"]["state"]["signals"], esc)
                self.assertEqual(esc["held"]["focus"], "svProbeBtn")

    #: The money controls on the fixture's /positions/, in the order the
    #: keyboard meets them, as c37e841 has them.
    MONEY_ORDER = [["a", "REAL MONEY · 1 BOT ARMED", "sv-armed-pill"], ["button", "CLOSE ALL", "svCloseAll"]] + [
        ["button", "CLOSE", "close-trade"]] * 5

    def test_doors_are_buttons_tab_reachable(self):
        """Every door is a native button in the Tab order: the menu (its
        fold row last), the top bar, the lane doors, the bar (THE HORDE
        before "N more"), the page, the dock, Gollum, the Eye. The rail's
        heads are buttons. The money controls keep their sequence."""
        for width, t in sorted(self.tabs.items()):
            r = t["rest"]
            with self.subTest(width=width, money=True):
                self.assertEqual(r["money"], self.MONEY_ORDER, json.dumps(r["money"], ensure_ascii=False))
            with self.subTest(width=width):
                for sel, tag, tab in r["doors"]:
                    self.assertEqual(tag, "BUTTON", sel)
                    self.assertGreaterEqual(tab, 0, sel)
                self.assertEqual(r["fold"], r["lastMenu"], r)
                z = [x for x in r["zones"] if x not in ("other",)]
                for a, b_ in (("skip", "menu"), ("menu", "topbar"), ("topbar", "doors"), ("doors", "band"), ("band", "bar"),
                              ("bar", "page"), ("page", "dock"), ("dock", "gollum"), ("gollum", "eye")):
                    self.assertIn(a, z, z)
                    self.assertIn(b_, z, z)
                    self.assertLess(z.index(a), z.index(b_), (a, b_, z))
                self.assertLess(r["prices"], r["news"])
                self.assertLess(r["horde"], r["more"])
                self.assertEqual(r["dock"], sorted(r["dock"]))
                self.assertLess(r["dock"][-1], r["gollum"])
                self.assertLess(r["gollum"], r["eye"])
                heads = t["heads"]
                self.assertEqual(len(heads), 2, heads)
                for h in heads:
                    self.assertTrue(h["button"], h)
                    self.assertIn(h["expanded"], ("true", "false"))
                    self.assertTrue(h["controls"])
                    self.assertGreaterEqual(h["tab"], 0)
                rail = t["rail"]
                self.assertGreater(rail["n"], r["n"])
                self.assertEqual(rail["heads"], 2, rail)

    def test_choices_follow_to_next_page(self):
        """The news put away and the Council opened on one page are the
        same on the next: the switch at the same box, away; the tab lit."""
        for width, f in sorted(self.follow.items()):
            with self.subTest(width=width):
                here, there = f["here"], f["there"]
                self.assertIsNotNone(there["news"])
                self.assertEqual(there["news"]["pressed"], "false")
                self.assertTrue(f["frame"]["news"]["collapsed"])
                for k in ("x", "y", "w", "h"):
                    self.assertAlmostEqual(there["news"]["box"][k], here["news"]["box"][k], delta=0.5)
                self.assertEqual(there["council"]["expanded"], "true")
                self.assertTrue(f["state"]["council"])

    def test_each_door_wears_its_colour(self):
        """The Council's icon is --sv-ai (violet), the Activity's --sv-cat-1
        (blue), at rest and lit, with a ring of the same on their counts; no
        door paints the Eye at rest, as a colour, a border, a fill or a
        stroke."""
        for width, theme, got in self.themes():
            for name, token in (("council", "--sv-ai"), ("activity", "--sv-cat-1")):
                with self.subTest(width=width, theme=theme, door=name):
                    d = got[name]
                    self.assertIsNotNone(d)
                    ico = [i for i in d["icons"] if "sv-door-ico" in i["cls"]]
                    self.assertEqual(len(ico), 1, d["icons"])
                    self.assertTrue(_near(ico[0]["stroke"], self.pal(theme, token)), (ico[0], token))
                    self.assertIsNotNone(d["badge"])
                    self.assertTrue(_near(d["badge"]["border"], self.pal(theme, token)), d["badge"])
                    lit = self.lit[(width, theme)][name]
                    ico = [i for i in lit["icons"] if "sv-door-ico" in i["cls"]]
                    self.assertTrue(_near(ico[0]["stroke"], self.pal(theme, token)), (ico[0], token))
            with self.subTest(width=width, theme=theme, door="dirs"):
                # SIGNALS' split: each side's glyph in its colour, its count
                # in ink, never the colour alone.
                ink = got["frame"]["dirsInk"]
                self.assertEqual([i["side"] for i in ink], ["up", "down"], ink)
                for i in ink:
                    self.assertTrue(_near(i["glyph"], self.pal(theme, "--sv-" + i["side"])), i)
                    self.assertTrue(_near(i["count"], self.pal(theme, "--sv-ink-1")), i)
            eye = self.pal(theme, "--sv-eye")
            for name, d in got.items():
                if name in ("eye", "frame") or not d:
                    continue
                with self.subTest(width=width, theme=theme, eye_paint=name):
                    self.assertFalse(_near(d["color"], eye, 6), d["color"])
                    self.assertFalse(_near(d["borderC"], eye, 6), d["borderC"])
                    self.assertFalse(_near(d["bg"], eye, 6), d["bg"])
                    for i in d["icons"]:
                        if "sv-ico" in i["cls"].split():
                            self.assertFalse(_near(i["stroke"], eye, 6), (name, i))
                    self.assertNotIn(re.sub(r"\s", "", "rgb(%d, %d, %d)" % _rgb(eye)), re.sub(r"\s", "", d["shadow"]))

    def test_quiet_and_lit(self):
        """Shut, a door is quiet: ink-2 words at 600 on bg-2 inside a line-3
        border. Open, it is lit: ink-1 words at 700; the Council and the
        Activity wash in their accent at 18 % on bg-1 inside a 60 % accent
        border, with a 2 px inset line of the accent on the panel's side;
        Signals and Ask on bg-3 with the Eye's 2 px inset line; the chevron
        turned."""
        for width, theme, got in self.themes():
            for name in DOCK + ("horde",):
                with self.subTest(width=width, theme=theme, quiet=name):
                    d = got[name]
                    self.assertIsNotNone(d)
                    self.assertTrue(_near(d["color"], self.pal(theme, "--sv-ink-2")), d["color"])
                    self.assertEqual(d["weight"], "600")
                    self.assertTrue(_near(d["bg"], self.pal(theme, "--sv-bg-2")), d["bg"])
                    self.assertEqual(d["borderW"], "1px")
                    self.assertTrue(_near(d["borderC"], self.pal(theme, "--sv-line-3")), d["borderC"])
                    self.assertEqual(d["face"], "Inter")
                    self.assertEqual((d["size"], d["tt"]), ("11px", "uppercase"))
            lit = self.lit[(width, theme)]
            for name in DOCK + ("horde",):
                with self.subTest(width=width, theme=theme, lit=name):
                    d, q = lit[name], got[name]
                    self.assertIsNotNone(d, name)
                    self.assertTrue(_near(d["color"], self.pal(theme, "--sv-ink-1")), d["color"])
                    self.assertEqual(d["weight"], "700")
                    chev = [i["transform"] for i in d["icons"] if "sv-door-chev" in i["cls"]]
                    chev0 = [i["transform"] for i in q["icons"] if "sv-door-chev" in i["cls"]]
                    self.assertEqual(len(chev), 1)
                    self.assertNotEqual(chev, chev0)
                    if name in ("council", "activity"):
                        token = {"council": "--sv-ai", "activity": "--sv-cat-1"}[name]
                        accent = self.pal(theme, token)
                        self.assertTrue(_near(d["bg"], _mix(accent, self.pal(theme, "--sv-bg-1"), 0.18), 3), d["bg"])
                        border = _parse(d["borderC"])
                        self.assertTrue(_near(d["borderC"], accent), d["borderC"])
                        self.assertAlmostEqual(border[3], 0.6, delta=0.02)
                        side = accent
                    else:
                        self.assertTrue(_near(d["bg"], self.pal(theme, "--sv-bg-3")), d["bg"])
                        side = self.pal(theme, "--sv-eye")
                    line = "inset 0px 2px 0px 0px" if name == "horde" else "inset 2px 0px 0px 0px"
                    shadow = re.sub(r"\s+", " ", d["shadow"])
                    self.assertIn("rgb(%d, %d, %d) " % _rgb(side) + line.replace("inset ", ""), shadow + " ")
                    self.assertIn("inset", shadow)
            with self.subTest(width=width, theme=theme, lit="eye"):
                eye = lit.get("eye")
                self.assertTrue(eye and eye["shown"] and eye["onTop"], eye)

    def test_contrast_dark_and_light(self):
        """Every word at 4.5:1 or more on its own ground, every icon at 3:1,
        every italic hint at 4.5:1: quiet, hovered, lit, put away; dark and
        light."""
        def check(label, d):
            if d.get("words"):
                c = contrast(_hex(_parse(d["color"])), _hex(_parse(d["wordGround"])))
                self.assertGreaterEqual(c, 4.5, "%s word %.2f" % (label, c))
            for i in d["icons"]:
                if not i["shown"] or i["inTip"]:
                    continue
                c = contrast(_hex(_parse(i["stroke"])), _hex(_parse(d["ground"])))
                self.assertGreaterEqual(c, 3, "%s icon %s %.2f" % (label, i["use"], c))
            if d.get("hint"):
                h = d["hint"]
                self.assertEqual(h["style"], "italic", label)
                self.assertGreaterEqual(float(h["size"].rstrip("px")), 12, label)
                c = contrast(_hex(_parse(h["color"])), _hex(_parse(h["ground"])))
                self.assertGreaterEqual(c, 4.5, "%s hint %.2f" % (label, c))
        for width, theme, got in self.themes():
            for name in WORDS:
                with self.subTest(width=width, theme=theme, state="quiet", door=name):
                    self.assertIsNotNone(got[name])
                    check("quiet %s" % name, got[name])
            for name, d in self.hover[(width, theme)].items():
                with self.subTest(width=width, theme=theme, state="hover", door=name):
                    check("hover %s" % name, d)
            for name, d in self.lit[(width, theme)].items():
                if name in ("gollum", "eye"):
                    continue
                with self.subTest(width=width, theme=theme, state="lit", door=name):
                    self.assertIsNotNone(d, name)
                    check("lit %s" % name, d)
            with self.subTest(width=width, theme=theme, state="away"):
                self.assertIsNotNone(self.away[(width, theme)])
                check("away news", self.away[(width, theme)])
        self.assertEqual(len(self.hover), 4)
        for key, hov in self.hover.items():
            self.assertEqual(sorted(hov), sorted(("prices", "signals", "council", "activity", "ask", "horde", "fold")), key)

    def test_icons_are_the_family(self):
        """Every icon of a door or a close is the sprite's (an <svg
        class="sv-ico"> using #svi-…), at the 1.5 stroke; no glyph is left
        standing for an icon (no ×, ⇔, ✕, ▼, no 16-unit arrow)."""
        for width, theme, got in self.themes():
            for name in WORDS:
                with self.subTest(width=width, theme=theme, door=name):
                    d = got[name]
                    self.assertIsNotNone(d)
                    self.assertEqual(d["glyphs"], "", name)
                    # The Horde's standards are its seats, drawn as data, not icons.
                    drawn = [i for i in d["icons"] if not i["inTip"] and "sv-seat" not in i["cls"].split()]
                    self.assertGreaterEqual(len(drawn), 1, name)
                    for i in drawn:
                        self.assertIn("sv-ico", i["cls"].split(), (name, i))
                        self.assertTrue((i["use"] or "").startswith("#svi-"), (name, i))
                        self.assertEqual(i["sw"], "1.5px", (name, i))
        for (width, name), closes in sorted(self.closes.items()):
            keys = {"council": ("council_x", "council_widen"), "activity": ("activity_x",), "horde": ("horde_x",),
                    "gollum": ("gollum_x",), "ask": ("ask_close",)}.get(name, ())
            for key in keys:
                with self.subTest(width=width, close=key):
                    c = closes[key]
                    self.assertIsNotNone(c)
                    self.assertEqual(re.sub(r"(?i)close", "", c["glyphs"]), "", c)
                    self.assertEqual(len(c["icons"]), 1, c)
                    self.assertTrue((c["icons"][0]["use"] or "").startswith("#svi-"), c)
                    self.assertEqual(c["icons"][0]["sw"], "1.5px", c)
        for key, heads in sorted(self.heads.items()):
            for h in heads:
                with self.subTest(at=key, head=h):
                    self.assertEqual(h["chev"]["tag"], "svg")
                    self.assertEqual(h["chev"]["use"], "#svi-chevron-down")
                    self.assertNotRegex(h["glyphs"], r"[▼◈◉]")

    def test_motion_short_and_off(self):
        """A door moves in 140 ms; under reduced motion and Ambience Off it
        does not move at all."""
        for name in ("prices", "signals", "council", "horde", "fold"):
            with self.subTest(door=name):
                d = self.motion["magic"][name]
                self.assertIsNotNone(d)
                self.assertIn("0.14s", d["transition"].split(", "), d["transition"])
                for k in ("off", "reduced"):
                    o = self.motion[k][name]
                    self.assertEqual(set(o["transition"].split(", ")), {"0s"}, (k, o["transition"]))
                    for i in o["icons"]:
                        self.assertEqual(set(i["transition"].split(", ")), {"0s"}, (k, name, i))
