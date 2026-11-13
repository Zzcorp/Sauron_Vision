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

This step builds the deal ticket; TAKE TRADE follows in the next.

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
