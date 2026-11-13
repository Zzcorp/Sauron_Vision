"""B6 of the desk v2: the deal ticket and TAKE TRADE as the board draws them.

The operator approved the desk v2 boards on 2026-11-13 ("amazing work,
bravo, I need it fast!!"). Ticket2 draws the ticket and its dialog, in
Sauron's identity, Bloomberg's discipline and TradingView's calm:

  * THE DEAL TICKET, on the instrument page: two fixed-width boxes, ▼ SHORT
    at the bid and ▲ LONG at the ask, the price in JetBrains Mono 15/500 in
    ink, the side in its colour on the label and the outline (coral, jade),
    never a fill; the REAL chip (the only solid red) and the spread between
    them; a stale ticket dashed, no price in ink, so none reads as fresh.
  * TAKE TRADE: the trade in the header (▲ LONG AUDUSD and the REAL chip),
    the question under it, a 3 px REAL top edge on a live order; the three
    steps (Review, PIN, Confirm the order) with "nothing is sent before
    step 3"; "⚠ 2 warnings", pinned under them, folding its list; each
    warning one amber title then its words; units beside the numbers (units,
    pips on a forex level); four figures (at the stop, at the target, reward
    to risk, margin at eToro); the PIN that says what it unlocks; Cancel
    neutral and the confirm in the side's colour, jade for a buy and coral
    for a sell, its words then the order under them ("TAKE LIVE TRADE",
    "▲ Long 20,000 AUDUSD"; "TAKE TRADE" on paper; "... ANYWAY" under the
    reward-to-risk floor).

What may never change (UI plan §10, binding): the words, the forms, the PIN
step, the confirm step and the focus order. The dialog's own words, fields
and gates are main's (read in base.html below); in the browser its fields,
their kinds, the first focus and the order a Tab walks are main's, the one
new stop being the summary's fold, which §10 itself asks for.

Measured in a headless Chromium (tests/test_close_advice.py's _Chrome) on
pages rendered through the test client from synthetic rows and opened as
files with their scripts dropped (tests/test_ui_s0_fixes._offline): the
ticket as the page prints it; the dialog built by the page's own TAKE TRADE
script, run in the page on a stubbed fetch that answers the preview (a
synthetic live payload, or the paper preview the server itself returned
for a synthetic signal) and refuses any order. Nothing is ever posted.

Display only. Money direction: none. No network, no broker, no model.

Run with:  python manage.py test tests.test_desk_v2_ticket
"""
import json
import pathlib
import re
import shutil
import tempfile
import unittest
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, HOST, _Chrome
from tests.test_design_tokens import PALETTE, decls, read, rules
from tests.test_ui_s0_fixes import _offline

ROOT = pathlib.Path(settings.BASE_DIR)
TICKET_CSS = "static/css/sv-ticket.css"
PARTIAL = "templates/_partials/deal_ticket.html"
BASE = "templates/base.html"


def rgb_of(hexv):
    h = hexv.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


UP, DOWN, REAL = rgb_of(PALETTE["--sv-up"]), rgb_of(PALETTE["--sv-down"]), rgb_of(PALETTE["--sv-real"])
WARN, DEMO = rgb_of(PALETTE["--sv-warn"]), rgb_of(PALETTE["--sv-demo"])
INK1, INK2, INK3 = (rgb_of(PALETTE[k]) for k in ("--sv-ink-1", "--sv-ink-2", "--sv-ink-3"))
WHITE = "rgb(255, 255, 255)"
#: Every colour the token sheet holds (the dark palette): a computed colour
#: is the token's own, or the token's at an alpha (a wash), or transparent.
TOKEN_RGB = {tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
             for v in PALETTE.values()} | {(255, 255, 255)}


def parse(c):
    m = re.match(r"rgba?\(([^)]+)\)", c or "")
    if not m:
        return None
    p = [float(x) for x in re.split(r"[ ,/]+", m.group(1).strip()) if x]
    return (p[0], p[1], p[2], p[3] if len(p) > 3 else 1.0)


def over(top, under):
    """`top` composited over the opaque `under`."""
    a = top[3]
    return tuple(top[i] * a + under[i] * (1 - a) for i in range(3)) + (1.0,)


def luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def ratio(fg, ground):
    """WCAG contrast of a text colour on its composited ground."""
    g = parse(ground)
    f = over(parse(fg), g)
    a, b = luminance(f), luminance(g)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def is_red_fill(c):
    p = parse(c)
    return bool(p) and p[3] >= 0.5 and p[0] >= 150 and p[1] < 130 and p[2] < 140


# ══════════════════════════════════════════════════════════════════════════
# The sheets and the markup
# ══════════════════════════════════════════════════════════════════════════

COLOUR_PROPS = ("color", "background", "background-color", "border", "border-color",
                "border-top", "border-right", "border-bottom", "border-left",
                "border-top-color", "border-left-color", "border-right-color",
                "border-bottom-color", "outline", "outline-color", "box-shadow",
                "text-decoration-color", "fill", "stroke", "accent-color", "caret-color")


class TicketSheetTests(SimpleTestCase):
    """static/css/sv-ticket.css, the batch's own sheet: tokens only, nothing
    under 11 px, no light, REAL the only solid red."""

    def setUp(self):
        self.css = read(TICKET_CSS)

    def test_the_sheet_names_only_tokens(self):
        offenders = []
        for prelude, body, ctx in rules(self.css):
            for prop, value in decls(body):
                if prop not in COLOUR_PROPS and not prop.startswith("--"):
                    continue
                bare = re.sub(r"var\(--[\w-]+\)", "", value)
                if re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgb|rgba|hsl|hsla|oklab|oklch)\(", bare) or \
                        re.search(r"\b(red|green|white|black|gold|orange|lime|yellow)\b", bare):
                    offenders.append("%s { %s: %s }" % (prelude, prop, value))
        self.assertEqual(offenders, [])

    def test_nothing_under_11px_and_no_light(self):
        offenders = []
        for prelude, body, ctx in rules(self.css):
            for prop, value in decls(body):
                if prop == "font-size":
                    m = re.fullmatch(r"([0-9.]+)px", value)
                    if m and float(m.group(1)) < 11:
                        offenders.append("%s { font-size: %s }" % (prelude, value))
                    if re.search(r"(^|[^.\d])0?\.\d+em|\d+%", value):
                        offenders.append("%s { font-size: %s } (relative)" % (prelude, value))
                if prop in ("text-shadow", "filter") and value != "none":
                    offenders.append("%s { %s: %s }" % (prelude, prop, value))
                if prop == "box-shadow" and value != "none":
                    offenders.append("%s { box-shadow: %s }" % (prelude, value))
                if "--sv-glow" in value or "--sv-spill" in value or "--sv-eye" in value:
                    offenders.append("%s { %s: %s }" % (prelude, prop, value))
        self.assertEqual(offenders, [])

    def test_real_is_the_only_solid_red(self):
        for prelude, body, ctx in rules(self.css):
            for prop, value in decls(body):
                if "--sv-real" in value:
                    with self.subTest(selector=prelude, prop=prop):
                        self.assertTrue(all(".tk-venue--live" in s for s in prelude.split(",")),
                                        prelude)
                if prop in ("background", "background-color") and re.search(r"--sv-down(?![\w-])", value):
                    with self.subTest(selector=prelude):
                        self.assertIn("transparent", value)      # a wash, never a fill


class DealTicketMarkupTests(SimpleTestCase):
    """The partial: its sheet, every hook a script reads, main's words."""

    def setUp(self):
        self.html = read(PARTIAL)

    def test_the_partial_brings_its_sheet(self):
        self.assertIn('<link rel="stylesheet" href="{% static \'css/sv-ticket.css\' %}">', self.html)
        self.assertIn("{% load static ", self.html)

    def test_every_hook_stays(self):
        for hook, n in (('data-ticket="{{ symbol }}"', 1), ("data-decimals=", 1),
                        ('data-dq="bid"', 1), ('data-dq="ask"', 1), ('data-dq="spread"', 1),
                        ('data-q="{{ symbol }}"', 3), ('data-q-f="bid"', 1), ('data-q-f="ask"', 1),
                        ('data-q-f="spread"', 1), ('<span class="sv-unknown">—</span>', 3),
                        ('class="tk-px"', 2), ('class="tk-v"', 1),
                        ("svTakeTradeAsset('{{ symbol|escapejs }}', 'SELL')", 1),
                        ("svTakeTradeAsset('{{ symbol|escapejs }}', 'BUY')", 1),
                        ('class="tk-side tk-short"', 1), ('class="tk-side tk-long"', 1),
                        ('class="tk-venue tk-venue--{{ lane_mode }}"', 1)):
            with self.subTest(hook=hook):
                self.assertEqual(self.html.count(hook), n)

    def test_main_s_words_stay_and_the_board_adds_the_quote_side(self):
        for words in ("▼ SHORT", "▲ LONG", "● LIVE", "◌ paper", "SPREAD",
                      'aria-label="Short {{ symbol }} at the bid"',
                      'aria-label="Long {{ symbol }} at the ask"',
                      'title="SHORT {{ symbol }} — hits the bid"',
                      'title="LONG {{ symbol }} — lifts the ask"'):
            with self.subTest(words=words):
                self.assertIn(words, self.html)
        self.assertIn('▼ SHORT<span class="tk-at"> · BID</span>', self.html)
        self.assertIn('▲ LONG<span class="tk-at"> · ASK</span>', self.html)


class TakeTradeSourceTests(SimpleTestCase):
    """The dialog's words, PIN step, confirm step and focus, as main wrote
    them, in base.html's TAKE TRADE script (§10: unchanged)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = read(BASE)
        at = src.index("function sizeDialog(p)")
        cls.fn = src[at:src.index("function tradeFlow(", at)]

    def test_main_s_words_and_gates_are_there_verbatim(self):
        for kept in (
                "'Take a second ' + p.symbol + ' ' + sideWord + (live ? ' with REAL funds?' : '?')",
                "(held.length ? 'Add to this LIVE position?' : 'Take this trade with REAL funds?')",
                "(held.length ? 'Add to this position?' : 'Take this trade?')",
                "? ('CLOSE ' + n + ' + TAKE')",
                ": (live ? 'TAKE LIVE TRADE'",
                ": ((held.length && !second) ? 'ADD' : 'TAKE TRADE'))) +",
                "(rrLow ? ' ANYWAY' : '');",
                "okBtn.disabled = !!(lvlWhy || sizeWhy) ||\n                         !!(live && pinIn && !pinIn.value);",
                "'<label class=\"sz-f\"><span>Required — real funds</span>'",
                "'<input type=\"password\" inputmode=\"numeric\" autocomplete=\"off\" '",
                "'data-role=\"pin\" placeholder=\"PIN\"></label>'",
                "data-role=\"cancel\">Cancel</button>",
                "'<button type=\"button\" class=\"sv-dialog-btn sv-dialog-btn--go' +",
                "host.setAttribute('data-sv-focus',",
                "second ? '[data-role=\"dupwarn\"]'",
                ": cashStop ? '[data-role=\"cashwarn\"]'",
                ": sizable ? '[data-role=\"qty\"]' : '[data-role=\"cancel\"]');",
                "pin: pinIn ? pinIn.value : null,",
                "qty: sendsAuto ? null : qtyVal,",
                "close_ids: ids,"):
            with self.subTest(kept=kept[:60]):
                self.assertIn(kept, self.fn)

    def test_the_pin_step_says_what_it_unlocks(self):
        self.assertIn("<legend>Trading PIN<span class=\"sz-pin-what\"> · places a live order "
                      "(real money)</span></legend>", self.fn)

    def test_the_confirm_wears_the_side_and_the_order(self):
        self.assertIn("host.setAttribute('data-side', buySide ? 'buy' : 'sell');", self.fn)
        self.assertIn("host.setAttribute('data-world', live ? 'live' : 'paper');", self.fn)
        self.assertIn("'sz-go-order'", self.fn)


# ══════════════════════════════════════════════════════════════════════════
# Measured
# ══════════════════════════════════════════════════════════════════════════

#: What every probe below reads, per element: the computed look, and the
#: ground under it composited from the element up to the first opaque one.
PROBE_LIB = r"""
function rgba(c) {
  var m = /rgba?\(([^)]+)\)/.exec(c || '');
  if (!m) return [0, 0, 0, 0];
  var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
  return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
}
function ground(el) {
  var stack = [];
  for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
    var c = rgba(getComputedStyle(e).backgroundColor);
    if (c[3] > 0) stack.push(c);
    if (c[3] >= 1) break;
  }
  var g = [0, 0, 0, 1];
  if (stack.length && stack[stack.length - 1][3] >= 1) g = stack.pop();
  while (stack.length) {
    var t = stack.pop();
    g = [t[0] * t[3] + g[0] * (1 - t[3]), t[1] * t[3] + g[1] * (1 - t[3]), t[2] * t[3] + g[2] * (1 - t[3]), 1];
  }
  return 'rgb(' + g.map(function (v) { return Math.round(v); }).slice(0, 3).join(', ') + ')';
}
function shown(el) {
  if (!el.getClientRects().length) return false;
  var c = getComputedStyle(el);
  return c.visibility !== 'hidden' && c.display !== 'none' && Number(c.opacity) > 0;
}
function texts(root) {
  var out = [];
  root.querySelectorAll('*').forEach(function (el) {
    if (!shown(el)) return;
    var own = Array.prototype.some.call(el.childNodes, function (n) {
      return n.nodeType === 3 && n.data.trim();
    });
    if (!own && !(el.tagName === 'INPUT' && el.value) && !(el.tagName === 'SELECT')) return;
    var c = getComputedStyle(el);
    out.push({ tag: el.tagName, cls: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className),
               text: (el.tagName === 'INPUT' ? el.value : el.textContent).trim().slice(0, 40),
               size: parseFloat(c.fontSize), color: c.color, ground: ground(el),
               off: !!el.closest('button[disabled]') });
  });
  return out;
}
function fills(root) {
  var out = [];
  [root].concat(Array.prototype.slice.call(root.querySelectorAll('*'))).forEach(function (el) {
    if (!shown(el)) return;
    var c = getComputedStyle(el);
    out.push({ cls: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className),
               tag: el.tagName, bg: c.backgroundColor, img: c.backgroundImage,
               color: c.color, borders: [[c.borderTopWidth, c.borderTopColor], [c.borderRightWidth, c.borderRightColor],
                                         [c.borderBottomWidth, c.borderBottomColor], [c.borderLeftWidth, c.borderLeftColor]],
               shadow: c.boxShadow, tshadow: c.textShadow, filter: c.filter });
  });
  return out;
}
function look(el) {
  if (!el) return null;
  var c = getComputedStyle(el), r = el.getBoundingClientRect();
  return { box: [r.left, r.top, r.width, r.height], color: c.color, bg: c.backgroundColor,
           img: c.backgroundImage, border: c.borderTopColor, bw: c.borderTopWidth,
           bstyle: c.borderTopStyle, lcolor: c.borderLeftColor, family: c.fontFamily,
           size: c.fontSize, weight: c.fontWeight, lh: c.lineHeight, shadow: c.boxShadow,
           tshadow: c.textShadow, text: (el.textContent || '').trim() };
}
"""

TICKET_PROBE = PROBE_LIB + r"""
(function () {
  var t = document.querySelector('.sv-ticket');
  var out = { order: Array.prototype.map.call(t.children, function (c) { return c.className; }) };
  var s = t.querySelector('.tk-short'), l = t.querySelector('.tk-long'), m = t.querySelector('.tk-mid');
  t.scrollIntoView({ block: 'center' });
  function side(b) {
    return { box: look(b), lbl: look(b.querySelector('.tk-lbl')), px: look(b.querySelector('.tk-px')) };
  }
  out.short = side(s); out.long = side(l); out.mid = look(m);
  out.chip = look(m.querySelector('.tk-venue')); out.spread = look(m.querySelector('.tk-v'));
  out.texts = texts(t); out.fills = fills(t);
  function boxes() { return [s, m, l].map(function (e) { var r = e.getBoundingClientRect();
                                                      return [r.left, r.top, r.width, r.height]; }); }
  var before = boxes();
  s.querySelector('.tk-px').textContent = '61234.56789';
  l.querySelector('.tk-px').textContent = '1.2';
  out.ticked = { before: before, after: boxes() };
  t.classList.add('tk-stale');
  t.querySelectorAll('[data-dq]').forEach(function (c) { c.innerHTML = '<span class="sv-unknown">—</span>'; });
  out.stale = { short: side(s), long: side(l), texts: texts(t) };
  return JSON.stringify(out);
})()
"""

DIALOG_PROBE = PROBE_LIB + r"""
(async function (SRC, OVERLAY, SCENARIOS) {
  await new Promise(function (ok, bad) {
    var s = document.createElement('script'); s.src = OVERLAY;
    s.onload = ok; s.onerror = function () { bad(new Error('sv-overlay.js did not load')); };
    document.head.appendChild(s);
  });
  (0, eval)(SRC);
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function opened() {
    for (var i = 0; i < 80; i++) {
      var d = document.querySelector('.sz-dialog.is-open');
      if (d) return d;
      await sleep(25);
    }
    throw new Error('no TAKE TRADE dialog opened');
  }
  function role(el) {
    if (!el) return null;
    if (el.getAttribute('data-role')) return el.getAttribute('data-role');
    if (el.classList.contains('sv-dialog-x')) return 'x';
    return el.tagName.toLowerCase();
  }
  function tabs(d) {
    return Array.prototype.filter.call(
      d.querySelectorAll('a[href], button, input, select, textarea, [tabindex]'),
      function (e) { return !e.disabled && e.tabIndex >= 0 && shown(e) && !e.closest('[hidden]'); }
    ).map(role);
  }
  function words(el) {
    if (!el) return null;
    return Array.prototype.filter.call(el.childNodes, function (n) { return n.nodeType === 3; })
      .map(function (n) { return n.data; }).join('').trim();
  }
  function measure(d) {
    var q = function (s) { return d.querySelector(s); };
    var c = getComputedStyle(d), r = d.getBoundingClientRect();
    var out = { box: [r.left, r.top, r.width, r.height], top: [c.borderTopWidth, c.borderTopColor],
                side: d.getAttribute('data-side'), world: d.getAttribute('data-world'),
                active: role(document.activeElement), tabs: tabs(d),
                head: look(q('.sv-dialog-head')), title: look(q('#svSizeTitle')),
                trade: look(q('.sz-trade')), tradeSide: look(q('.sz-trade .sz-side')),
                tradeSym: look(q('.sz-trade .sz-sym')), chip: look(q('.sz-trade .sv-world')),
                steps: look(q('.sz-steps')), wsum: look(q('[data-role="wsum"]')),
                wsumText: look(q('[data-role="wsumtext"]')), go: look(q('[data-role="ok"]')),
                goWords: words(q('[data-role="ok"]')), goOrder: look(q('[data-role="ok"] .sz-go-order')),
                cancel: look(q('[data-role="cancel"]')), body: look(q('.sv-dialog-body')),
                okDisabled: q('[data-role="ok"]').disabled };
    var steps = d.querySelectorAll('.sz-steps .sz-step');
    out.stepList = Array.prototype.map.call(steps, function (li) {
      return { text: li.textContent.trim(), current: li.getAttribute('aria-current'),
               done: li.classList.contains('is-done') };
    });
    out.stepsNote = q('.sz-steps-note') ? q('.sz-steps-note').textContent.trim() : null;
    var ws = q('[data-role="wsum"]');
    out.wsumHidden = ws ? ws.hidden : null;
    out.wsumExpanded = ws ? ws.getAttribute('aria-expanded') : null;
    var list = q('[data-role="warns"]');
    out.warnsShown = list ? shown(list) && !list.hidden : null;
    out.warns = list ? Array.prototype.filter.call(list.querySelectorAll('.sz-warn'), function (w) {
      return !w.hidden && !w.closest('[hidden]');
    }).map(function (w) {
      return { title: look(w.querySelector('b')), box: look(w) };
    }) : [];
    out.units = {};
    ['qty', 'cash', 'notional', 'stop', 'target'].forEach(function (k) {
      var i = q('[data-role="' + k + '"]');
      var u = i && i.parentElement && i.parentElement.querySelector('.sz-u');
      out.units[k] = { input: look(i), unit: u ? u.textContent.trim() : null,
                       well: look(i && i.parentElement) };
    });
    out.figs = Array.prototype.map.call(d.querySelectorAll('.sz-figs .sz-fig'), function (f) {
      return { k: f.querySelector('.sz-fig-k').textContent.trim(), box: look(f),
               v: look(f.querySelector('.sz-fig-v')) };
    });
    var pin = q('[data-role="pin"]');
    out.pin = pin ? { type: pin.type, inputmode: pin.getAttribute('inputmode'),
                      autocomplete: pin.getAttribute('autocomplete'), placeholder: pin.placeholder,
                      label: pin.closest('fieldset').textContent.replace(/\s+/g, ' ').trim(),
                      look: look(pin) } : null;
    out.fields = Array.prototype.map.call(d.querySelectorAll('input, select'), function (i) {
      return [role(i), i.tagName.toLowerCase(), i.getAttribute('type'), i.getAttribute('inputmode'),
              i.getAttribute('autocomplete'), i.getAttribute('placeholder')];
    });
    out.forms = d.querySelectorAll('form').length;
    out.texts = texts(d); out.fills = fills(d);
    out.vh = window.innerHeight;
    return out;
  }
  var all = {};
  for (var k = 0; k < SCENARIOS.length; k++) {
    var sc = SCENARIOS[k], posted = [];
    window.fetch = function (url) {
      url = String(url);
      if (url.indexOf('/take-trade/preview/') !== -1) {
        return Promise.resolve(new Response(JSON.stringify(sc.payload),
          { status: 200, headers: { 'Content-Type': 'application/json' } }));
      }
      if (/\/take-trade\/$/.test(url)) {
        posted.push(url);
        return Promise.reject(new Error('this test never sends an order'));
      }
      return Promise.resolve(new Response('{}', { status: 200,
        headers: { 'Content-Type': 'application/json' } }));
    };
    if (sc.signal) window.svTakeTrade(sc.signal);
    else window.svTakeTradeAsset(sc.payload.symbol, sc.payload.side);
    var d = await opened();
    await sleep(300);
    var got = { open: measure(d) };
    var ws = d.querySelector('[data-role="wsum"]');
    if (ws && !ws.hidden) {
      ws.click(); await sleep(30);
      got.folded = measure(d);
      ws.click(); await sleep(30);
      got.unfolded = measure(d);
    }
    var pin = d.querySelector('[data-role="pin"]');
    if (pin) {
      pin.focus(); pin.dispatchEvent(new Event('focus')); await sleep(30);
      got.pinFocused = measure(d);
      pin.value = '0000'; pin.dispatchEvent(new Event('input', { bubbles: true })); await sleep(30);
      got.pinTyped = measure(d);
    }
    d.querySelector('[data-role="cancel"]').click();
    for (var i = 0; i < 40 && document.contains(d); i++) await sleep(25);
    await sleep(50);
    got.posted = posted;
    all[sc.name] = got;
  }
  return JSON.stringify(all);
})
"""


#: The live BUY opened again, its body at the top: where each warning's
#: ⚠ mark is drawn (its ::before, 14 px at the line's left), to be read in
#: a picture of it.
MARKS_PROBE = r"""
(async function (PAYLOAD) {
  window.fetch = function (url) {
    if (String(url).indexOf('/take-trade/preview/') !== -1) {
      return Promise.resolve(new Response(JSON.stringify(PAYLOAD),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    if (/\/take-trade\/$/.test(String(url))) return Promise.reject(new Error('never sent'));
    return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
  };
  window.svTakeTradeAsset(PAYLOAD.symbol, PAYLOAD.side);
  var d = null;
  for (var i = 0; i < 80 && !d; i++) {
    d = document.querySelector('.sz-dialog.is-open');
    if (!d) await new Promise(function (r) { setTimeout(r, 25); });
  }
  await new Promise(function (r) { setTimeout(r, 300); });
  d.querySelector('.sv-dialog-body').scrollTop = 0;
  await new Promise(function (r) { setTimeout(r, 100); });
  return JSON.stringify(Array.prototype.map.call(
    d.querySelectorAll('[data-role="warns"] .sz-warn'), function (w) {
      var r = w.getBoundingClientRect();
      return [r.left, r.top + 2, 14, 14];
    }));
})
"""


def _amber_share(png_b64):
    """The share of a picture's pixels in the warning amber's family."""
    import base64
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    px = list(im.getdata())
    hits = sum(1 for r, g, b in px if r > 170 and 100 < g < 200 and b < 120 and r - b > 90)
    return hits / float(len(px))


def _instrument(symbol, cls, name):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": name, "asset_class": cls, "is_active": True})
    return inst


def _two_sided(symbol, cls, name, bid, ask):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, cls, name)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": (Decimal(bid) + Decimal(ask)) / 2,
                                   "bid": Decimal(bid), "ask": Decimal(ask), "source": "etoro"})
    return inst


def _live_payload(side="BUY", warnings=2, target=None):
    """A synthetic LIVE preview, the board's AUDUSD: 20,000 units at 30x,
    stop 36 pips away, target 72 (or `target`), eToro's cells read; the two
    board warnings when asked. Never sent anywhere."""
    buy = side == "BUY"
    fill = 0.6542 if buy else 0.65412
    p = {
        "symbol": "AUDUSD", "side": side, "qty": 20000.0, "entry": fill,
        "stop": round(fill - 0.0036 if buy else fill + 0.0036, 5),
        "target": target if target is not None else round(fill + 0.0072 if buy else fill - 0.0072, 5),
        "stop_widened": False, "risk_dollars": 72.0, "notional": 13084.0, "capital_use": 436.13,
        "capital": 10453.61, "committed": 1200.0, "available": 3000.0, "sufficient": True,
        "deficit": 0.0, "close_proposal": [], "closable": [], "managed": True, "venue": "live",
        "mark_delayed": False, "requires_pin": True, "asset_class": "forex", "cap_class": "forex",
        "value_per_unit": 1.0, "qty_step": 1.0, "risk_per_unit": 0.0036,
        "notional_per_unit": fill, "capital_use_per_unit": fill / 30, "pool_free": 3000.0,
        "max_qty": 120000.0, "venue_min_qty": None, "venue_min_note": "", "smallest_size": None,
        "max_risk_dollars": 209.07, "max_notional": 100000.0, "book_single_position": {},
        "book_limits": [],
        "levels": {"fill": fill, "min_stop_fraction": 0.0003, "max_stop_fraction": 0.03,
                   "min_stop_pct_text": "0.030", "max_stop_pct_text": "3.0", "asset_class": "forex",
                   "cost_fraction": 0.0002, "cost_filter": True, "min_edge_ratio": 3.0,
                   "min_net_rr": 1.0, "reward_risk_warn": 1.0, "levels_note": ""},
        "leverage": {"effective": 30, "adjustable": True, "choices": [1, 2, 5, 10, 20, 30],
                     "chosen": 30, "max": 30, "why": "",
                     "note": ("30x — eToro locks notional / 30 as margin; the risk is the stop's, "
                              "whatever the multiplier. Open for this ticket: 1x, 2x, 5x, 10x, 20x, 30x.")},
        "existing_exposure": [], "concentration": {}, "duplicate": {},
        "cash_gate": {"asked": True, "ok": True, "reason": "", "cash": 2400.0, "used": 3200.0,
                      "equity": 10453.61, "currency": "USD", "age_s": 12, "age_words": "12 s",
                      "equity_age_words": "40 s", "free": 2400.0, "room": 2400.0,
                      "max_qty": 110000.0, "margin_per_unit": fill / 30, "pnl": 76.26,
                      "pledged": 0, "refresh": {"asked": False}},
        "theme": {}, "cost_advisory": {"ok": True}, "rule_advisory": {}, "risk_appetite": {"pct": 0.69},
        "venue_health": {"ok": True}, "timing_advisory": {"ok": True}, "short_advisory": {"ok": True},
        "proof_advisory": {"ok": True}, "quote_advisory": {"ok": True}, "setup_memory": {},
        "positioning": {}, "council_on": False, "book_advisory": {"ok": True},
        "signal_backing": {"ok": True},
    }
    if warnings >= 1:
        p["book_advisory"] = {"ok": False, "reason": (
            "With this order the real book stands at 2.44% of eToro equity at the stops; "
            "the limit is 2.50%.")}
    if warnings >= 2:
        p["signal_backing"] = {"ok": False, "reason": (
            "The rail holds no AUDUSD %s; this order is yours." % ("long" if buy else "short"))}
    return p


def _take_trade_source(html):
    """The page's own TAKE TRADE script, as the page renders it."""
    at = html.index("function sizeDialog(p)")
    start = html.rindex("(function () {", 0, at)
    return html[start:html.index("})();", html.index("window.svCloseTrade", at)) + len("})();")]


def _open_pages(pages, probe):
    """{url: the probe's answer} at 1440 x 900, one Chromium."""
    tmp = tempfile.mkdtemp(prefix="sv-b6-")
    try:
        chrome = _Chrome(CHROME)
        try:
            sid = chrome.page(1440, 900, False)
            got = {}
            for i, (url, (markup, expr)) in enumerate(sorted(pages.items())):
                path = pathlib.Path(tmp) / ("page%d.html" % i)
                path.write_text(_offline(markup), encoding="utf-8")
                chrome.open(sid, path.as_uri())
                got[url] = json.loads(chrome.eval(sid, expr))
            return got
        finally:
            chrome.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _Desk(TestCase):

    @classmethod
    def setUpTestData(cls):
        from bot_program.manual_trade import manual_config_for
        cls.user = get_user_model().objects.create_user("b6_desk", password="x", is_staff=True,
                                                        is_superuser=True)
        _two_sided("AUDUSD", "forex", "Australian Dollar / US Dollar", "0.65412", "0.65420")
        cfg = manual_config_for(cls.user, "forex")
        cfg.mode = "live"
        cfg.save(update_fields=["mode"])
        cls.client_ = Client()
        cls.client_.force_login(cls.user)

    @classmethod
    def page(cls, url):
        resp = cls.client_.get(url, HTTP_HOST=HOST)
        if resp.status_code != 200:
            raise AssertionError("%s answered %s" % (url, resp.status_code))
        return resp.content.decode("utf-8")


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DealTicketMeasuredTests(_Desk):
    """The ticket on /instruments/AUDUSD/ (a live forex lane), at 1440."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        url = "/instruments/AUDUSD/"
        cls.got = _open_pages({url: (cls.page(url), TICKET_PROBE)}, None)[url]

    def test_short_mid_long_in_that_order(self):
        self.assertEqual([c.split()[0:2] for c in self.got["order"]],
                         [["tk-side", "tk-short"], ["tk-mid"], ["tk-side", "tk-long"]])

    def test_the_board_s_geometry(self):
        s, m, l = (self.got[k]["box"]["box"] if k != "mid" else self.got["mid"]["box"]
                   for k in ("short", "mid", "long"))
        self.assertAlmostEqual(s[2], l[2], delta=0.5)        # two boxes of one width
        self.assertGreaterEqual(s[2], 118)
        self.assertAlmostEqual(m[2], 92, delta=0.5)          # the middle column
        self.assertAlmostEqual(m[0] - (s[0] + s[2]), 10, delta=0.5)
        self.assertAlmostEqual(l[0] - (m[0] + m[2]), 10, delta=0.5)
        self.assertAlmostEqual(s[1], l[1], delta=0.5)
        self.assertAlmostEqual(s[3], l[3], delta=0.5)

    def test_a_ticking_price_never_moves_a_button(self):
        self.assertEqual(self.got["ticked"]["before"], self.got["ticked"]["after"])

    def test_the_sides_wear_their_colour_on_the_label_and_the_outline_never_a_fill(self):
        for k, hue in (("short", DOWN), ("long", UP)):
            box, lbl = self.got[k]["box"], self.got[k]["lbl"]
            with self.subTest(side=k):
                self.assertEqual(lbl["color"], hue)
                # 1.5 px, as Chromium draws it at this density (1 px at 1x)
                self.assertEqual(box["border"], hue)
                self.assertIn(box["bw"], ("1px", "1.5px"))
                self.assertFalse(is_red_fill(box["bg"]))
                self.assertEqual(box["img"], "none")
                self.assertEqual((box["shadow"], box["tshadow"]), ("none", "none"))

    def test_the_price_is_a_figure_in_ink_15_500_and_the_label_inter_11_600(self):
        for k in ("short", "long"):
            px, lbl = self.got[k]["px"], self.got[k]["lbl"]
            with self.subTest(side=k):
                self.assertTrue(px["family"].startswith('"JetBrains Mono"'), px["family"])
                self.assertEqual((px["size"], px["weight"], px["color"]), ("15px", "500", INK1))
                self.assertTrue(lbl["family"].startswith("Inter"), lbl["family"])
                self.assertEqual((lbl["size"], lbl["weight"]), ("11px", "600"))
                # one line: a label never wraps under its price
                self.assertLessEqual(lbl["box"][3], float(lbl["lh"][:-2]) + 0.5, lbl)
        self.assertIn("· BID", self.got["short"]["lbl"]["text"])
        self.assertIn("· ASK", self.got["long"]["lbl"]["text"])

    def test_the_real_chip_and_the_spread_between_them(self):
        chip = self.got["chip"]
        self.assertEqual((chip["bg"], chip["color"]), (REAL, WHITE))
        self.assertIn("LIVE", chip["text"])
        self.assertTrue(self.got["spread"]["family"].startswith('"JetBrains Mono"'))
        mid, chip_box = self.got["mid"]["box"], chip["box"]
        self.assertGreaterEqual(chip_box[0], mid[0] - 0.5)
        self.assertLessEqual(chip_box[0] + chip_box[2], mid[0] + mid[2] + 0.5)

    def test_no_text_under_11px_and_every_word_at_4_5_to_1(self):
        for t in self.got["texts"] + self.got["stale"]["texts"]:
            with self.subTest(text=t["text"], cls=t["cls"]):
                self.assertGreaterEqual(t["size"], 11)
                self.assertGreaterEqual(ratio(t["color"], t["ground"]), 4.5)

    def test_tokens_only_and_real_the_only_solid_red(self):
        for f in self.got["fills"]:
            with self.subTest(cls=f["cls"], tag=f["tag"]):
                if is_red_fill(f["bg"]):
                    self.assertIn("tk-venue--live", f["cls"])
                for c in [f["color"], f["bg"]] + [b[1] for b in f["borders"] if parse(b[0] + ",")
                                                  or float(b[0][:-2] or 0) > 0]:
                    p = parse(c)
                    if p and p[3] > 0:
                        self.assertIn(tuple(round(v) for v in p[:3]), TOKEN_RGB, c)
                self.assertEqual((f["tshadow"], f["filter"]), ("none", "none"))

    def test_a_stale_ticket_prints_no_price_as_fresh(self):
        stale = self.got["stale"]
        for k in ("short", "long"):
            with self.subTest(side=k):
                self.assertEqual(stale[k]["px"]["text"], "—")
                self.assertNotEqual(stale[k]["px"]["color"], INK1)
                self.assertEqual(stale[k]["box"]["bstyle"], "dashed")
                self.assertNotIn(stale[k]["lbl"]["color"], (UP, DOWN))


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TakeTradeMeasuredTests(_Desk):
    """TAKE TRADE on /instruments/AUDUSD/ at 1440: a live BUY with the
    board's two warnings, a live SELL, a live BUY under the reward-to-risk
    floor (synthetic payloads), and a paper ticket on the preview the server
    returned for a synthetic signal."""

    #: main's fields, by role: (role, tag, type, inputmode, autocomplete, placeholder)
    LIVE_FIELDS = [["stop", "input", "number", "decimal", None, None],
                   ["target", "input", "number", "decimal", None, None],
                   ["lev", "select", None, None, None, None],
                   ["qty", "input", "number", "decimal", None, None],
                   ["cash", "input", "number", "decimal", None, None],
                   ["notional", "input", "number", "decimal", None, None],
                   ["pin", "input", "password", "numeric", "off", "PIN"]]
    #: main's Tab order on a live ticket at open (the confirm waits for the PIN)
    LIVE_TABS = ["x", "stop", "target", "lev", "qty", "cash", "notional", "pin", "cancel"]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.test_take_trade import _quote, _signal
        sig = _signal(_quote("BTCUSD", 60600), entry=60600, stop=59700, target=62400)
        resp = cls.client_.post("/signals/%d/take-trade/preview/" % sig.id, data="{}",
                                content_type="application/json", HTTP_HOST=HOST)
        cls.paper = resp.json()
        url = "/instruments/AUDUSD/"
        html = cls.page(url)
        scenarios = [
            {"name": "live_buy", "payload": _live_payload("BUY")},
            {"name": "live_sell", "payload": _live_payload("SELL")},
            {"name": "live_floor", "payload": _live_payload("BUY", warnings=0, target=0.6560)},
            {"name": "paper", "payload": cls.paper, "signal": sig.id},
        ]
        expr = DIALOG_PROBE + "(%s, %s, %s)" % (
            json.dumps(_take_trade_source(html)),
            json.dumps((ROOT / "static/js/sv-overlay.js").as_uri()), json.dumps(scenarios))
        tmp = tempfile.mkdtemp(prefix="sv-b6-")
        try:
            path = pathlib.Path(tmp) / "page.html"
            path.write_text(_offline(html), encoding="utf-8")
            chrome = _Chrome(CHROME)
            try:
                sid = chrome.page(1440, 900, False)
                chrome.open(sid, path.as_uri())
                cls.got = json.loads(chrome.eval(sid, expr))
                rects = json.loads(chrome.eval(sid, MARKS_PROBE + "(%s)" % json.dumps(_live_payload("BUY"))))
                cls.marks = [_amber_share(chrome.call("Page.captureScreenshot", {
                    "format": "png", "clip": {"x": x, "y": y, "width": w, "height": h, "scale": 2}},
                    session=sid)["data"]) for x, y, w, h in rects]
            finally:
                chrome.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_server_s_paper_preview_is_a_paper_buy(self):
        self.assertNotIn("error", self.paper, self.paper)
        self.assertEqual((self.paper["venue"], self.paper["side"]), ("paper", "BUY"))

    def test_nothing_was_ever_sent(self):
        for name, got in self.got.items():
            with self.subTest(scenario=name):
                self.assertEqual(got["posted"], [])

    def test_the_header_names_the_trade_with_its_world(self):
        for name, side, hue, chip, bg in (("live_buy", "▲ LONG", UP, "REAL", REAL),
                                          ("live_sell", "▼ SHORT", DOWN, "REAL", REAL),
                                          ("paper", "▲ LONG", UP, "PAPER", None)):
            o = self.got[name]["open"]
            with self.subTest(scenario=name):
                self.assertEqual(o["tradeSide"]["text"], side)
                self.assertEqual(o["tradeSide"]["color"], hue)
                self.assertTrue(o["tradeSym"]["family"].startswith('"JetBrains Mono"'))
                self.assertEqual(o["chip"]["text"], chip)
                if bg:
                    self.assertEqual((o["chip"]["bg"], o["chip"]["color"]), (bg, WHITE))
                else:
                    self.assertFalse(is_red_fill(o["chip"]["bg"]))
                # the trade on one line, the question under it, in the 56 px head
                self.assertAlmostEqual(o["head"]["box"][3], 56, delta=1)
                self.assertLess(o["trade"]["box"][1], o["title"]["box"][1])
        self.assertEqual(self.got["live_buy"]["open"]["title"]["text"], "Take this trade with REAL funds?")
        self.assertEqual(self.got["paper"]["open"]["title"]["text"], "Take this trade?")

    def test_a_live_order_carries_the_real_top_edge_and_paper_does_not(self):
        for name in ("live_buy", "live_sell", "live_floor"):
            with self.subTest(scenario=name):
                self.assertEqual(self.got[name]["open"]["top"], ["3px", REAL])
        self.assertNotEqual(self.got["paper"]["open"]["top"][1], REAL)

    def test_the_dialog_is_the_board_s_width(self):
        for name, got in self.got.items():
            with self.subTest(scenario=name):
                self.assertAlmostEqual(got["open"]["box"][2], 580, delta=1)

    def test_three_steps_and_nothing_is_sent_before_the_last(self):
        live = self.got["live_buy"]
        self.assertEqual([s["text"] for s in live["open"]["stepList"]],
                         ["1Review", "2PIN", "3Confirm the order"])
        self.assertEqual(live["open"]["stepsNote"], "nothing is sent before step 3")
        self.assertAlmostEqual(live["open"]["steps"]["box"][3], 34, delta=1)
        cur = lambda m: [s["text"][1:] for s in m["stepList"] if s["current"] == "step"]
        self.assertEqual(cur(live["open"]), ["Review"])
        self.assertEqual(cur(live["pinFocused"]), ["PIN"])
        self.assertEqual(cur(live["pinTyped"]), ["Confirm the order"])
        self.assertEqual([s["done"] for s in live["pinTyped"]["stepList"]], [True, True, False])
        paper = self.got["paper"]["open"]
        self.assertEqual([s["text"] for s in paper["stepList"]], ["1Review", "2Confirm the order"])
        self.assertEqual(paper["stepsNote"], "nothing is sent before step 2")

    def test_the_summary_counts_the_warnings_inside_the_first_view(self):
        for name in ("live_buy", "live_sell"):
            o = self.got[name]["open"]
            with self.subTest(scenario=name):
                self.assertFalse(o["wsumHidden"])
                self.assertEqual(len(o["warns"]), 2)
                self.assertEqual(o["wsumText"]["text"], "2 warnings")
                self.assertEqual(o["wsumExpanded"], "true")
                box, dlg = o["wsum"]["box"], o["box"]
                self.assertAlmostEqual(box[3], 34, delta=1)
                self.assertGreaterEqual(box[1], dlg[1])
                self.assertLessEqual(box[1] + box[3], min(dlg[1] + 160, o["vh"]))
                self.assertEqual(o["wsumText"]["color"], WARN)
        floor = self.got["live_floor"]["open"]
        self.assertEqual(len(floor["warns"]), 1)          # YOU RISK MORE THAN YOU CAN WIN
        self.assertEqual(floor["wsumText"]["text"], "1 warning")

    def test_the_summary_folds_its_list_and_names_what_it_folded(self):
        got = self.got["live_buy"]
        self.assertTrue(got["open"]["warnsShown"])
        self.assertEqual(got["folded"]["wsumExpanded"], "false")
        self.assertFalse(got["folded"]["warnsShown"])
        self.assertEqual(got["folded"]["wsumText"]["text"],
                         "2 warnings: BOOK LIMIT REACHED · NO SAURON SIGNAL BEHIND THIS TRADE")
        self.assertEqual(got["unfolded"]["wsumExpanded"], "true")
        self.assertTrue(got["unfolded"]["warnsShown"])

    def test_each_warning_carries_its_mark_as_painted(self):
        """The ⚠ before each warning is drawn, in the warning amber (a mark
        that fails to load leaves nothing on the screen: read in a picture)."""
        self.assertEqual(len(self.marks), 2)
        for share in self.marks:
            self.assertGreater(share, 0.05)

    def test_each_warning_is_an_amber_title_never_demo_gold(self):
        for name in ("live_buy", "live_sell", "live_floor"):
            for w in self.got[name]["open"]["warns"]:
                with self.subTest(scenario=name, title=w["title"]["text"]):
                    self.assertEqual(w["title"]["color"], WARN)
                    self.assertGreaterEqual(float(w["title"]["size"][:-2]), 11)
                    for c in (w["box"]["color"], w["box"]["bg"], w["box"]["border"]):
                        self.assertNotEqual(c, DEMO)
                        p = parse(c)
                        self.assertFalse(p and p[3] > 0 and tuple(round(v) for v in p[:3]) == (214, 188, 94), c)

    def test_units_beside_the_numbers(self):
        u = self.got["live_buy"]["open"]["units"]
        self.assertEqual(u["qty"]["unit"], "units")
        self.assertEqual(u["stop"]["unit"], "-36 pips")
        self.assertEqual(u["target"]["unit"], "+72 pips")
        s = self.got["live_sell"]["open"]["units"]
        self.assertEqual((s["stop"]["unit"], s["target"]["unit"]), ("+36 pips", "-72 pips"))
        for k in ("qty", "stop", "target"):
            with self.subTest(field=k):
                self.assertAlmostEqual(u[k]["well"]["box"][3], 32, delta=1)
                self.assertTrue(u[k]["input"]["family"].startswith('"JetBrains Mono"'))
        # a paper crypto level is a distance in percent, not pips
        p = self.got["paper"]["open"]["units"]
        self.assertRegex(p["stop"]["unit"] or "", r"^-\d+\.\d\d%$")

    def test_the_four_figures(self):
        figs = self.got["live_buy"]["open"]["figs"]
        self.assertEqual([f["k"] for f in figs],
                         ["At the stop", "At the target", "Reward : risk", "Margin at eToro"])
        self.assertEqual([f["v"]["text"] for f in figs], ["-$72.00", "+$144.00", "2.00", "436.13 USD"])
        self.assertEqual((figs[0]["v"]["color"], figs[1]["v"]["color"]), (DOWN, UP))
        tops = {round(f["box"]["box"][1]) for f in figs}
        widths = [f["box"]["box"][2] for f in figs]
        self.assertEqual(len(tops), 1)                  # one row
        self.assertLess(max(widths) - min(widths), 1.5)  # four equal cells
        for f in figs:
            self.assertTrue(f["v"]["family"].startswith('"JetBrains Mono"'))
        paper = [f["k"] for f in self.got["paper"]["open"]["figs"]]
        self.assertEqual(paper[-1], "Cash committed")

    def test_the_pin_keeps_its_kind_and_says_what_it_unlocks(self):
        pin = self.got["live_buy"]["open"]["pin"]
        self.assertEqual((pin["type"], pin["inputmode"], pin["autocomplete"], pin["placeholder"]),
                         ("password", "numeric", "off", "PIN"))
        self.assertIn("Trading PIN · places a live order (real money)", pin["label"])
        self.assertIn("Required — real funds", pin["label"])
        self.assertIsNone(self.got["paper"]["open"]["pin"])

    def test_the_confirm_takes_the_side_s_colour_and_says_the_order(self):
        for name, hue, words, order in (
                ("live_buy", UP, "TAKE LIVE TRADE", "▲ Long 20,000 AUDUSD"),
                ("live_sell", DOWN, "TAKE LIVE TRADE", "▼ Short 20,000 AUDUSD"),
                ("live_floor", UP, "TAKE LIVE TRADE ANYWAY", "▲ Long 20,000 AUDUSD")):
            m = self.got[name]["pinTyped"]
            with self.subTest(scenario=name):
                self.assertFalse(m["okDisabled"])
                self.assertEqual(m["goWords"], words)
                self.assertEqual(m["goOrder"]["text"], order)
                self.assertEqual((m["go"]["color"], m["go"]["border"]), (hue, hue))
                self.assertIn(m["go"]["bw"], ("1px", "1.5px"))   # 1.5 px, snapped at 1x
                self.assertFalse(is_red_fill(m["go"]["bg"]))
                self.assertEqual((m["go"]["img"], m["go"]["shadow"]), ("none", "none"))
                self.assertAlmostEqual(m["go"]["box"][3], 42, delta=1)
                self.assertAlmostEqual(m["cancel"]["box"][3], 42, delta=1)
                self.assertEqual(m["cancel"]["color"], INK1)
                self.assertNotIn(m["cancel"]["border"], (UP, DOWN))
        paper = self.got["paper"]["open"]
        self.assertEqual(paper["goWords"], "TAKE TRADE")
        self.assertEqual(paper["go"]["color"], UP)
        # before the PIN the live confirm is off, and looks it: no side colour
        off = self.got["live_buy"]["open"]
        self.assertTrue(off["okDisabled"])
        self.assertNotIn(off["go"]["color"], (UP, DOWN))

    def test_main_s_fields_first_focus_and_tab_order(self):
        o = self.got["live_buy"]["open"]
        self.assertEqual(o["fields"], self.LIVE_FIELDS)
        self.assertEqual(o["forms"], 0)
        self.assertEqual(o["active"], "qty")
        self.assertEqual([t for t in o["tabs"] if t != "wsum"], self.LIVE_TABS)
        self.assertEqual(self.got["live_buy"]["pinTyped"]["tabs"][-2:], ["cancel", "ok"])
        # the one new stop, the summary's fold (§10 asks for it), right
        # under the head: before every field, after the head's ×
        self.assertEqual(o["tabs"][:2], ["x", "wsum"])
        self.assertEqual(o["tabs"].count("wsum"), 1)

    def test_no_text_under_11px_and_every_word_at_4_5_to_1(self):
        for name, got in self.got.items():
            for state in ("open", "pinTyped"):
                if state not in got:
                    continue
                for t in got[state]["texts"]:
                    with self.subTest(scenario=name, state=state, text=t["text"], cls=t["cls"]):
                        self.assertGreaterEqual(t["size"], 11)
                        if not t["off"]:     # an inactive control is exempt (WCAG 1.4.3)
                            self.assertGreaterEqual(ratio(t["color"], t["ground"]), 4.5)

    def test_tokens_only_no_light_and_real_the_only_solid_red(self):
        for name, got in self.got.items():
            for f in got["open"]["fills"] + got.get("pinTyped", got["open"])["fills"]:
                with self.subTest(scenario=name, cls=f["cls"], tag=f["tag"]):
                    if is_red_fill(f["bg"]):
                        self.assertIn("sv-world--live", f["cls"])
                    colours = [f["color"], f["bg"]] + [c for w, c in f["borders"] if float(w[:-2]) > 0]
                    for c in colours:
                        p = parse(c)
                        if p and p[3] > 0:
                            self.assertIn(tuple(round(v) for v in p[:3]), TOKEN_RGB, c)
                    self.assertEqual((f["tshadow"], f["filter"]), ("none", "none"))
                    self.assertNotIn("gradient", f["img"])
                    # no light: a shadow is a ring with no blur (the focus
                    # ring of a field) or the dialog's black drop, never a glow
                    for layer in re.split(r",\s*(?=rgba?\()", f["shadow"]):
                        if layer == "none":
                            continue
                        blur = re.findall(r"(-?[\d.]+)px", layer)[2]
                        if float(blur) > 0:
                            self.assertEqual(parse(layer)[:3], (0, 0, 0), layer)
