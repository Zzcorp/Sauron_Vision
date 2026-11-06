"""/design/kit/: the kit on one page, for staff (UI plan §7, S1a, 2026-11-06).

Every component of static/css/sv-kit.css on synthetic content: the palette
and the type scale, the shell's quote and status cells, the table with a
row per money world, tiles, a key-value grid, a meter, sparklines, the five
chips and the price badges, every button variant, the controls, notices,
the empty state, a popover and a real-money dialog, and the two number
filters (qty, src_name) on made-up values.

  * ONLY STAFF SEE IT: a signed-in user who is not staff, and a visitor who
    is not signed in, get the 404 an unknown URL gets (no login redirect
    that would say the page exists).
  * EVERY COMPONENT IS ON IT, and nothing on it acts: every button is a
    plain type="button" with no handler, no field sits in a form, nothing
    is posted, and the view reads no model.
  * THE NUMBER RULES: qty trims, groups and keeps eight significant digits;
    src_name prints a source's name, never its tag; unknown is the em-dash.
  * MEASURED, at the four desk widths: nothing on the page under 11 px, no
    sideways scroll, every component drawn, REAL white on its red, the
    market colours only on BUY and SELL.

Display only. Run with:  python manage.py test tests.test_design_kit_page
"""
import pathlib
import re
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from core.templatetags.sauron_tags import qty, src_name
from tests.test_close_advice import CHROME, HOST
from tests.test_design_tokens import PALETTE, rgb
from tests.test_ui_s0_fixes import _measure

ROOT = pathlib.Path(settings.BASE_DIR)
URL = "/design/kit/"

#: What the page must show: a marker in its markup for each component.
COMPONENTS = {
    "palette swatches": 'data-kit="swatch"',
    "type scale": 'data-kit="type"',
    "quote cells": 'data-kit="quote-cells"',
    "status cells": 'data-kit="status-cells"',
    "the live heartbeat": 'class="sv-live-dot"',
    "the armed pill": 'class="sv-armed-pill"',
    "table": 'class="sv-table"',
    "the REAL row edge": 'class="sv-row--live"',
    "REAL chip": "sv-world sv-world--live",
    "DEMO chip": "sv-world sv-world--demo",
    "PAPER chip": "sv-world sv-world--paper",
    "side chips": "sv-side sv-side--up",
    "neutral chip": 'class="sv-chip"',
    "state chips": "sv-state sv-state--off",
    "count": 'class="sv-count"',
    "model mark": 'class="sv-ai"',
    "estimate chip": 'class="sv-est"',
    "price badges": "sv-fresh sv-fresh--stale",
    "reference badge": "sv-fresh sv-fresh--ref",
    "P&L cell": 'class="sv-pnl-src"',
    "KPI tiles": 'class="sv-kpi"',
    "key-value grid": 'class="sv-kv',
    "score meter": 'class="sv-meter-track"',
    "sparkline": "sv-spark sv-spark--up",
    "primary button": "btn btn-primary",
    "secondary button": "btn btn-secondary",
    "ghost button": "btn btn-ghost",
    "BUY button": "btn btn-buy",
    "SELL button": "btn btn-sell",
    "stop button": "btn btn-stop",
    "icon button": "btn btn-icon",
    "protective outline": "btn btn-danger",
    "disabled button with its reason": 'disabled title="',
    "button sizes": "btn btn-lg",
    "input": "sv-input sv-input--num",
    "PIN field": "sv-input sv-pin-field",
    "checkbox": 'type="checkbox"',
    "radio": 'type="radio"',
    "display toggle": 'class="sv-toggle"',
    "tabs": 'class="sv-tabs"',
    "segmented control": 'class="sv-seg"',
    "menu": "sv-menu dk-static-menu",
    "notices": "sv-notice sv-notice--warn",
    "danger notice": "sv-notice sv-notice--danger",
    "empty state": 'class="sv-empty-state"',
    "popover": 'class="sv-popover"',
    "real-money dialog": "sv-dialog sv-dialog--danger",
    "number rules": 'data-kit="numbers"',
}


def _user(name, **kw):
    return get_user_model().objects.create_user(name, password="x", **kw)


class DesignKitAccessTests(TestCase):

    def test_the_route(self):
        self.assertEqual(reverse("design_kit"), URL)

    def test_staff_sees_the_page(self):
        client = Client()
        client.force_login(_user("kit_staff", is_staff=True))
        resp = client.get(URL, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "dashboard/design_kit.html")
        self.assertContains(resp, "The design kit")

    def test_a_superuser_sees_it_too(self):
        client = Client()
        client.force_login(_user("kit_root", is_staff=False, is_superuser=True))
        self.assertEqual(client.get(URL, HTTP_HOST=HOST).status_code, 200)

    def test_a_signed_in_user_who_is_not_staff_gets_404(self):
        client = Client()
        client.force_login(_user("kit_user"))
        self.assertEqual(client.get(URL, HTTP_HOST=HOST).status_code, 404)

    def test_a_visitor_gets_404_not_a_login_redirect(self):
        self.assertEqual(Client().get(URL, HTTP_HOST=HOST).status_code, 404)


class DesignKitContentTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        client = Client()
        client.force_login(_user("kit_reader", is_staff=True))
        cls.html = client.get(URL, HTTP_HOST=HOST).content.decode("utf-8")
        start = cls.html.index('<div class="dk-page">')
        cls.page = cls.html[start:cls.html.index("<!-- /dk-page -->")]

    def test_every_component_is_on_the_page(self):
        missing = [name for name, marker in COMPONENTS.items()
                   if marker not in self.page]
        self.assertEqual(missing, [])

    def test_the_topbar_names_the_page(self):
        """The topbar says where you are, not base.html's "Dashboard"
        (2026-11-06)."""
        self.assertIn('<span class="topbar-title">Design kit</span>', self.html)

    def test_every_token_of_the_palette_is_shown(self):
        for token, hexv in PALETTE.items():
            if token == "--sv-real-ink":
                continue
            with self.subTest(token=token):
                self.assertIn("var(%s)" % token, self.page)
                self.assertIn(hexv, self.page)

    def test_nothing_on_it_acts(self):
        buttons = re.findall(r"<button\b[^>]*>", self.page)
        self.assertGreater(len(buttons), 20)
        for tag in buttons:
            with self.subTest(button=tag):
                self.assertIn('type="button"', tag)
                self.assertNotIn("onclick", tag)
                self.assertNotRegex(tag, r"\bhx-")
                self.assertNotRegex(tag, r"\bdata-sv-")
        self.assertNotIn("<form", self.page)
        self.assertNotIn("<script", self.page)

    def test_the_view_reads_no_data(self):
        src = (ROOT / "dashboard" / "views_design_kit.py").read_text(encoding="utf-8")
        imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, flags=re.M)
        self.assertEqual(sorted(imports), ["core.views_book", "django.http", "django.shortcuts"])

    def test_the_number_rules_render(self):
        for want in ("20,000", "0.05", "1.5", "0.12345679", "Yahoo", "Binance",
                     "eToro", "OANDA", "Finnhub"):
            with self.subTest(value=want):
                self.assertIn("<dd>%s</dd>" % want, self.page)
        self.assertIn("<dd>—</dd>", self.page)
        self.assertNotIn("<dd>20000.00000000</dd>", self.page)


class NumberFilterTests(SimpleTestCase):
    """§4.4: quantities trimmed and grouped; sources by name."""

    def test_qty(self):
        for value, want in (("20000.00000000", "20,000"), ("0.05000000", "0.05"),
                            ("1.50000000", "1.5"), ("12.00000000", "12"),
                            ("0.123456789", "0.12345679"), (-1234.5, "-1,234.5"),
                            ("0", "0"), (0, "0"), ("0.00012345678", "0.00012345678"),
                            ("1,234.50", "1,234.5")):
            with self.subTest(value=value):
                self.assertEqual(qty(value), want)

    def test_qty_says_unknown_and_leaves_what_is_not_a_number(self):
        self.assertEqual(qty(None), "—")
        self.assertEqual(qty(""), "—")
        self.assertEqual(qty("n/a"), "n/a")

    def test_src_name(self):
        for tag, want in (("yfinance_public", "Yahoo"), ("yfinance", "Yahoo"),
                          ("binance_public", "Binance"), ("binance_ws", "Binance"),
                          ("etoro", "eToro"), ("oanda_stream", "OANDA"),
                          ("finnhub_ws", "Finnhub"), ("paper", "paper"),
                          ("PAPER", "paper"), ("ibkr", "IBKR")):
            with self.subTest(tag=tag):
                self.assertEqual(src_name(tag), want)

    def test_src_name_never_prints_a_tag(self):
        self.assertEqual(src_name("some_new_feed"), "some new feed")
        self.assertEqual(src_name(None), "—")
        self.assertEqual(src_name(""), "—")


KIT_PROBE = r"""(function () {
    var W = innerWidth, de = document.documentElement;
    var out = { width: W, docOverflowX: de.scrollWidth - de.clientWidth, small: [], blocks: {} };
    var page = document.querySelector('.dk-page');
    Array.prototype.forEach.call(document.body.querySelectorAll('*'), function (el) {
        if (el.closest('script,style,noscript,template')) return;
        if (el.closest('.grid-bg,.eye-glow-shadow,.globe-eye-bg,.globe-circuits-bg,#particles-canvas,#caustics-canvas,.se-cs-paragraph')) return;
        var own = false;
        for (var i = 0; i < el.childNodes.length; i++) {
            var n = el.childNodes[i];
            if (n.nodeType === 3 && n.nodeValue.trim()) { own = true; break; }
        }
        if (!own) return;
        var fs = parseFloat(getComputedStyle(el).fontSize);
        if (fs < 11) out.small.push((el.className && el.className.baseVal === undefined ? el.tagName + '.' + el.className : el.tagName) + '@' + fs);
    });
    Array.prototype.forEach.call(page.querySelectorAll('[data-kit]'), function (el) {
        var b = el.getBoundingClientRect();
        var k = el.getAttribute('data-kit');
        out.blocks[k] = Math.max(out.blocks[k] || 0, Math.round(b.width * b.height));
    });
    function paint(sel) {
        var el = page.querySelector(sel); if (!el) return null;
        var c = getComputedStyle(el);
        return { bg: c.backgroundColor, color: c.color, border: c.borderTopColor, top: c.borderTopWidth };
    }
    out.real = paint('.sv-world--live'); out.demo = paint('.sv-world--demo'); out.paper = paint('.sv-world--paper');
    out.buy = paint('.btn-buy'); out.sell = paint('.btn-sell'); out.stop = paint('.btn-stop');
    out.primary = paint('.btn-primary'); out.danger = paint('.btn-danger');
    out.dialog = paint('.sv-dialog--danger');
    return JSON.stringify(out);
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class DesignKitMeasuredTests(TestCase):

    VIEWPORTS = ((1280, 800), (1440, 900), (1920, 1080), (2560, 1440))

    @classmethod
    def setUpTestData(cls):
        client = Client()
        client.force_login(_user("kit_measure", is_staff=True))
        page = client.get(URL, HTTP_HOST=HOST).content.decode("utf-8")
        cls.got = {w: g for (u, w), g in
                   _measure({URL: page}, cls.VIEWPORTS, KIT_PROBE, "sv-s1a-kit-").items()}

    def test_nothing_under_11px_anywhere_on_it(self):
        for width, got in sorted(self.got.items()):
            with self.subTest(width=width):
                self.assertEqual(got["small"], [])

    def test_no_sideways_scroll(self):
        for width, got in sorted(self.got.items()):
            with self.subTest(width=width):
                self.assertEqual(got["docOverflowX"], 0)

    def test_every_component_is_drawn(self):
        for width, got in sorted(self.got.items()):
            for block, area in got["blocks"].items():
                with self.subTest(width=width, block=block):
                    self.assertGreater(area, 0)
            self.assertGreaterEqual(len(got["blocks"]), 20, got["blocks"])

    def test_the_worlds_and_the_market_colours(self):
        got = self.got[1440]
        self.assertEqual(got["real"]["bg"], rgb(PALETTE["--sv-real"]))
        self.assertEqual(got["real"]["color"], "rgb(255, 255, 255)")
        self.assertEqual(got["demo"]["color"], rgb(PALETTE["--sv-demo"]))
        self.assertEqual(got["demo"]["bg"], "rgba(0, 0, 0, 0)")
        self.assertEqual(got["paper"]["color"], rgb(PALETTE["--sv-ink-3"]))
        self.assertEqual(got["buy"]["color"], rgb(PALETTE["--sv-up"]))
        self.assertEqual(got["buy"]["border"], rgb(PALETTE["--sv-up"]))
        self.assertEqual(got["sell"]["color"], rgb(PALETTE["--sv-down"]))
        self.assertEqual(got["sell"]["border"], rgb(PALETTE["--sv-down"]))
        for name in ("stop", "danger"):
            self.assertEqual(got[name]["bg"], "rgba(0, 0, 0, 0)", name)
            self.assertEqual(got[name]["color"], rgb(PALETTE["--sv-ink-1"]), name)
        self.assertEqual(got["primary"]["bg"], rgb(PALETTE["--sv-ink-1"]))
        self.assertEqual(got["primary"]["color"], rgb(PALETTE["--sv-bg-0"]))
        self.assertEqual(got["dialog"]["top"], "3px")
        self.assertEqual(got["dialog"]["border"], rgb(PALETTE["--sv-real"]))
