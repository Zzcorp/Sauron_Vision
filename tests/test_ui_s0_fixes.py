"""S0 of the UI plan: six display defects, fixed and pinned (2026-11-06).

Display only. Nothing pinned here, and nothing in the change it pins,
reaches an order, a stop, a size, a gate, a switch or a broker. Every page
is rendered by the test client from synthetic rows and laid out in a
headless Chromium with every network URL blocked.

What each class pins:

  * THE RAIL NO LONGER COVERS THE PAGE. The signal rail is a fixed column
    on the right (44 px shut, 280 px open) and .main-content keeps a margin
    for it. On /positions/ and /portfolio/, the two pages that carry the
    selection bar, sv-close-advice.css makes .main-content clip instead of
    hide so the bar can stick, and clip is not a scroll container: the
    column's automatic minimum width became its widest content's, and the
    page ran under the rail (on the synthetic fixture: 44 px with the rail
    shut, 280 px open at 1280 and 1440, 33 px at 1920, 159 px on
    /portfolio/). Measured at 1280, 1440 and 1920, rail shut and open.
  * WHAT THE COLUMN'S FIT COSTS IS PAID FOR (the S0 review). Held to its
    track, the column scrolls a wide table in its wrapper, and the row's
    CLOSE sat past the wrapper's edge until the table was scrolled (cut to
    "CLOS…" at 1680 with the rail shut and at 1920 with it open, where
    main showed it whole). The action column is pinned to the wrapper's
    right edge: CLOSE whole in view at 1280, 1440, 1680 and 1920, rail
    shut and open, scrolled or not, a click on it landing on it; the row's
    tint, stripe and hover ground painted on the pinned cell; a hairline
    and a shadow on its left edge, so a figure cut there reads as cut. The
    small cards above /positions/' table keep 300 px each, so the
    asset-class table's P&L is not cut mid-figure or hidden.
  * THE TICKET'S PRICES ARE IN THE PAGE'S FACE. The bid and the ask print
    on <button>s, and a button does not inherit its font: they, and the
    side labels above them, printed in the browser's Arial beside a spread
    in the mono face.
  * /SIGNALS/ DRAWS ITS CHARTS. Its metrics arrive as an htmx fragment
    that brings Chart.js. htmx re-creates the scripts of what it swaps in,
    the library's script then loads in the background, and the inline chart
    code ran first: "Chart is not defined", and no chart. The swap is
    replayed here the way htmx 1.9.10 does it, with a stand-in library
    served from a data: URL (its own hash in the integrity check), twice:
    the second time as the minute's refresh does it.
  * THE CHART CREDITS TRADINGVIEW. lightweight-charts is TradingView's,
    under the Apache License 2.0, and its licence asks for the NOTICE's
    attribution and a link to https://www.tradingview.com/ on a page the
    users see.
  * NATIVE CONTROLS FOLLOW THE THEME. With no colour scheme the browser
    paints what no rule dresses in its light default on the dark theme: in
    Chromium a button left unstyled and the frame of a select's open list,
    in Firefox the page's scrollbars too. (Chromium's scrollbars and the
    date inputs were dressed by their own rules already.) Pinned here as
    the scheme the root and a native control compute.
  * A LINK NO CLASS STYLES IS READABLE. It took the browser's blue on the
    void (/orcs/ "Orc #13"); it is the text colour now, underlined at 40 %
    and fully on hover. (A link whose colour something else sets keeps that
    colour; its underline takes the 40 % tint of it.)

The measured classes drive the Chromium of tests/test_close_advice.py
(CHROME, _Chrome) and are skipped, not failed, where the machine has none.

Run with:  python manage.py test tests.test_ui_s0_fixes
"""
import base64
import hashlib
import json
import pathlib
import re
import shutil
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_close_advice import (CHROME, HOST, _Chrome, _instrument,
                                     _legacy, _quote, _trade)

ROOT = pathlib.Path(settings.BASE_DIR)

#: Where _chart_assets.html loads Chart.js from. The measured signals test
#: serves its stand-in in this URL's place.
CHART_JS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"

#: The licence's link, as the credit under the chart carries it.
CREDIT_LINK = 'href="https://www.tradingview.com/"'


def _read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _offline(page):
    """A rendered page as a file Chromium can open on its own: scripts
    dropped (they want a server; the layout does not), external
    stylesheets dropped (no network), /static/ read from the tree. The
    same treatment as test_close_advice's measured bar."""
    page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
    page = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", page)
    return page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)


def _get(client, url):
    resp = client.get(url, HTTP_HOST=HOST)
    if resp.status_code != 200:
        raise AssertionError("%s answered %s" % (url, resp.status_code))
    return resp.content.decode("utf-8")


def _two_sided_quote(symbol, bid, ask, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst,
        defaults={"last": (Decimal(bid) + Decimal(ask)) / 2,
                  "bid": Decimal(bid), "ask": Decimal(ask),
                  "source": "test"})


def _measure(pages, viewports, probe, tmp_prefix):
    """{(url, width): the probe's answer} for each page at each viewport,
    one Chromium for the lot. `pages` maps a url to its rendered markup."""
    tmp = tempfile.mkdtemp(prefix=tmp_prefix)
    try:
        files = {}
        for i, (url, markup) in enumerate(sorted(pages.items())):
            path = pathlib.Path(tmp) / ("page%d.html" % i)
            path.write_text(_offline(markup), encoding="utf-8")
            files[url] = path.as_uri()
        chrome = _Chrome(CHROME)
        try:
            got = {}
            for width, height in viewports:
                sid = chrome.page(width, height, False)
                for url, uri in files.items():
                    chrome.open(sid, uri)
                    got[(url, width)] = json.loads(chrome.eval(sid, probe))
            return got
        finally:
            chrome.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════
# 1. The rail and the page
# ══════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class RailOverlapMeasuredTests(TestCase):
    """The page's right edge stops at the rail's left edge, rail shut and
    rail open, at the three desk widths, on both pages that carry the
    selection bar. The book holds a bot row and a legacy row, so the
    positions table is there and wider than the column at every width."""

    PAGES = ("/positions/", "/portfolio/")
    VIEWPORTS = ((1280, 800), (1440, 900), (1920, 1080))

    #: The rail's state is the page script's (localStorage); the scripts
    #: are dropped, so the probe sets the class the script would. Every
    #: transition is finished before a box is read: the rail eases its
    #: width over 0.3 s.
    PROBE = r"""(async function () {
        function frame() {
            return new Promise(function (r) {
                requestAnimationFrame(function () { requestAnimationFrame(r); });
            });
        }
        function finish() {
            document.getAnimations().forEach(function (a) {
                try { a.finish(); } catch (e) {}
            });
        }
        var rail = document.querySelector(".signals-rail");
        var page = document.querySelector(".page-content");
        var main = document.querySelector(".main-content");
        var out = { width: window.innerWidth };
        var states = ["closed", "open"];
        for (var i = 0; i < states.length; i++) {
            rail.classList.toggle("open", states[i] === "open");
            void getComputedStyle(rail).width;
            finish();
            await frame();
            finish();
            var r = rail.getBoundingClientRect();
            out[states[i]] = {
                railShown: getComputedStyle(rail).display !== "none",
                railLeft: r.left, railWidth: r.width,
                pageRight: page.getBoundingClientRect().right,
                mainRight: main.getBoundingClientRect().right
            };
        }
        return JSON.stringify(out);
    })()"""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s0_rail", password="x")
        _quote("BTCUSD", 60600)
        _trade(user)
        _legacy(user)
        client = Client()
        client.force_login(user)
        pages = {url: _get(client, url) for url in cls.PAGES}
        for url, markup in pages.items():
            # The pages this defect lives on: the ones with the bar.
            if "data-sv-select-bar" not in markup:
                raise AssertionError("%s no longer carries the selection "
                                     "bar" % url)
        cls.got = _measure(pages, cls.VIEWPORTS, cls.PROBE, "sv-s0-rail-")

    def test_the_probe_sees_the_rail_it_set(self):
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertEqual(got["width"], width)
                for state, wide in (("closed", 44), ("open", 280)):
                    self.assertTrue(got[state]["railShown"], got)
                    self.assertAlmostEqual(got[state]["railWidth"], wide,
                                           delta=0.5, msg=got)

    def test_the_page_stops_at_the_rail(self):
        for (url, width), got in sorted(self.got.items()):
            for state in ("closed", "open"):
                box = got[state]
                with self.subTest(url=url, width=width, rail=state):
                    self.assertLessEqual(
                        box["pageRight"], box["railLeft"] + 0.5,
                        "%s at %d px, rail %s: the page runs %.0f px under "
                        "the rail" % (url, width, state,
                                      box["pageRight"] - box["railLeft"]))
                    self.assertLessEqual(box["mainRight"],
                                         box["railLeft"] + 0.5, box)


# ══════════════════════════════════════════════════════════════════════════
# 1b. What the column's own width costs the tables (S0 review, 2026-11-06)
# ══════════════════════════════════════════════════════════════════════════
#
# With the column held to its track, a table wider than it scrolls in its
# own wrapper instead of running under the rail. The review measured what
# that cost: on the synthetic fixture the row's CLOSE, whole on main at
# 1680 with the rail shut and at 1920 with it open (the column then ran
# under the rail by its padding only), was cut to 68 % and 73 % ("CLOS…"),
# and it had already needed a sideways scroll at 1280 and 1440; and the
# small cards above the table shrank until the asset-class table's
# "unreal P&L" figure was cut mid-number or out of view.

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class CloseInViewMeasuredTests(TestCase):
    """Every row's CLOSE on /positions/ and /portfolio/ is whole in view
    with the table not scrolled, still in view with the table scrolled to
    its far end, and a click at its centre lands on it (never on the rail,
    never on a cell scrolled over it), at four desk widths, rail shut and
    open. And what the row paints (a ticked row's tint, an even row's
    stripe, the hover ground) reaches the pinned cell, so the column reads
    as part of its row, and its left edge says the columns go on under
    it."""

    PAGES = ("/positions/", "/portfolio/")
    VIEWPORTS = ((1280, 800), (1440, 900), (1680, 1050), (1920, 1080))

    PROBE = r"""(async function () {
        function frame() {
            return new Promise(function (r) {
                requestAnimationFrame(function () { requestAnimationFrame(r); });
            });
        }
        function finish() {
            document.getAnimations().forEach(function (a) {
                try { a.finish(); } catch (e) {}
            });
        }
        var rail = document.querySelector(".signals-rail");
        function look(b, wrap) {
            var r = b.getBoundingClientRect(), w = wrap.getBoundingClientRect();
            var left = w.left + wrap.clientLeft, right = left + wrap.clientWidth;
            var x = r.left + r.width / 2, y = r.top + r.height / 2;
            var top = document.elementFromPoint(x, y);
            return { left: r.left, right: r.right, visLeft: left, visRight: right,
                     railLeft: rail.getBoundingClientRect().left,
                     hit: !!top && (top === b || b.contains(top)),
                     on: top ? String(top.className || top.tagName).slice(0, 40) : null };
        }
        var out = { width: window.innerWidth, states: {} };
        var states = ["closed", "open"];
        for (var i = 0; i < states.length; i++) {
            rail.classList.toggle("open", states[i] === "open");
            void getComputedStyle(rail).width;
            finish();
            await frame();
            finish();
            var rows = [];
            var buttons = document.querySelectorAll(".table-wrapper [data-sv-close-trade]");
            for (var j = 0; j < buttons.length; j++) {
                var b = buttons[j], wrap = b.closest(".table-wrapper");
                wrap.scrollLeft = 0;
                window.scrollTo(0, 0);
                window.scrollTo(0, b.getBoundingClientRect().top - window.innerHeight / 2);
                await frame();
                var start = look(b, wrap);
                wrap.scrollLeft = wrap.scrollWidth;
                await frame();
                var end = look(b, wrap);
                wrap.scrollLeft = 0;
                b.scrollIntoView({ block: "center", inline: "nearest" });
                await frame();
                var reach = look(b, wrap);
                rows.push({ start: start, end: end, reach: reach,
                            scrollWidth: wrap.scrollWidth,
                            clientWidth: wrap.clientWidth });
                wrap.scrollLeft = 0;
                window.scrollTo(0, 0);
            }
            out.states[states[i]] = rows;
        }
        return JSON.stringify(out);
    })()"""

    #: A cell pinned over the others paints its own ground, so what the row
    #: paints has to reach it: a ticked row's tint (on its cells), the
    #: zebra of an even row and the hover ground (on the row). Each is in
    #: the last cell's paint, or the last cell lets it through.
    ROW_PROBE = r"""(async function (phase) {
        function frame() {
            return new Promise(function (r) {
                requestAnimationFrame(function () { requestAnimationFrame(r); });
            });
        }
        function finish() {
            document.getAnimations().forEach(function (a) {
                try { a.finish(); } catch (e) {}
            });
        }
        var row = document.querySelector(".table-wrapper [data-sv-close-trade]")
                          .closest("tr");
        var even = row.parentElement.querySelector(":scope > tr:nth-child(even)");
        if (phase === "tick") {
            finish();
            window.scrollTo(0, row.getBoundingClientRect().top - window.innerHeight / 2);
        }
        // Ticked for the first read; the hover is read on an unticked row,
        // so the ground is the hover's alone.
        row.querySelector(".sv-sel-box").checked = phase === "tick";
        await frame();
        finish();
        function paint(tr) {
            var cells = tr.querySelectorAll(":scope > td");
            function one(el) {
                var c = getComputedStyle(el);
                return { color: c.backgroundColor, image: c.backgroundImage,
                         position: c.position };
            }
            return { row: one(tr), last: one(cells[cells.length - 1]),
                     other: one(cells[2]) };
        }
        var r = row.querySelectorAll(":scope > td")[2].getBoundingClientRect();
        var cells = row.querySelectorAll(":scope > td");
        var last = cells[cells.length - 1];
        var shade = getComputedStyle(last, "::before");
        return JSON.stringify({
            x: r.left + r.width / 2, y: r.top + r.height / 2,
            hover: row.matches(":hover"),
            first: paint(row), even: even ? paint(even) : null,
            edge: { line: getComputedStyle(last).boxShadow,
                    shade: { content: shade.content, image: shade.backgroundImage,
                             width: parseFloat(shade.width) || 0,
                             position: shade.position } }
        });
    })(%s)"""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s0_close", password="x")
        _quote("BTCUSD", 60600)
        _trade(user)
        _legacy(user)
        client = Client()
        client.force_login(user)
        pages = {url: _get(client, url) for url in cls.PAGES}
        for url, markup in pages.items():
            if "data-sv-close-trade" not in markup:
                raise AssertionError("%s shows no CLOSE to measure" % url)
        cls.got = _measure(pages, cls.VIEWPORTS, cls.PROBE, "sv-s0-close-")
        tmp = tempfile.mkdtemp(prefix="sv-s0-closerow-")
        try:
            path = pathlib.Path(tmp) / "positions.html"
            path.write_text(_offline(pages["/positions/"]), encoding="utf-8")
            chrome = _Chrome(CHROME)
            try:
                sid = chrome.page(1440, 900, False)
                chrome.open(sid, path.as_uri())
                cls.ticked = json.loads(chrome.eval(sid, cls.ROW_PROBE % '"tick"'))
                chrome.call("Input.dispatchMouseEvent",
                            {"type": "mouseMoved", "x": cls.ticked["x"],
                             "y": cls.ticked["y"]}, session=sid)
                cls.hovered = json.loads(chrome.eval(sid, cls.ROW_PROBE % '"hover"'))
            finally:
                chrome.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _each(self):
        for (url, width), got in sorted(self.got.items()):
            for state, rows in sorted(got["states"].items()):
                for i, row in enumerate(rows):
                    yield url, width, state, i, row

    def test_every_page_and_width_has_a_close_to_measure(self):
        for (url, width), got in sorted(self.got.items()):
            for state in ("closed", "open"):
                with self.subTest(url=url, width=width, rail=state):
                    self.assertEqual(got["width"], width)
                    self.assertGreaterEqual(len(got["states"][state]), 1, got)

    def test_the_positions_table_is_wider_than_its_wrapper_somewhere(self):
        """What makes the checks below mean something: at 1280 the book's
        table does not fit its column, so CLOSE in view there is the pin's
        doing, not room to spare."""
        rows = self.got[("/positions/", 1280)]["states"]["open"]
        self.assertTrue(any(r["scrollWidth"] > r["clientWidth"] + 20
                            for r in rows), rows)

    def test_close_is_whole_in_view_with_the_table_not_scrolled(self):
        for url, width, state, i, row in self._each():
            box = row["start"]
            with self.subTest(url=url, width=width, rail=state, row=i):
                self.assertGreaterEqual(box["left"], box["visLeft"] - 0.5, row)
                self.assertLessEqual(
                    box["right"], box["visRight"] + 0.5,
                    "%s at %d px, rail %s: CLOSE runs %.0f px past what the "
                    "table shows" % (url, width, state,
                                     box["right"] - box["visRight"]))
                self.assertLessEqual(box["right"], box["railLeft"] + 0.5, row)
                self.assertTrue(box["hit"], row)

    def test_close_stays_in_view_with_the_table_scrolled_to_its_end(self):
        for url, width, state, i, row in self._each():
            box = row["end"]
            with self.subTest(url=url, width=width, rail=state, row=i):
                self.assertGreaterEqual(box["left"], box["visLeft"] - 0.5, row)
                self.assertLessEqual(box["right"], box["visRight"] + 0.5, row)
                self.assertTrue(box["hit"], row)

    def test_brought_into_view_a_click_lands_on_close_never_the_rail(self):
        for url, width, state, i, row in self._each():
            with self.subTest(url=url, width=width, rail=state, row=i):
                self.assertTrue(row["reach"]["hit"], row)
                self.assertLessEqual(row["reach"]["right"],
                                     row["reach"]["railLeft"] + 0.5, row)

    CLEAR = ("rgba(0, 0, 0, 0)", "transparent")

    def _reaches(self, colour, last, got):
        """`colour` is painted in the last cell, or the cell is clear and
        what lies under it shows through."""
        self.assertNotIn(colour, self.CLEAR, got)
        clear = last["color"] in self.CLEAR and last["image"] == "none"
        self.assertTrue(clear or colour == last["color"]
                        or colour in last["image"], got)

    def test_a_ticked_rows_tint_reaches_its_last_cell(self):
        first = self.ticked["first"]
        self._reaches(first["other"]["color"], first["last"], self.ticked)

    def test_an_even_rows_stripe_reaches_its_last_cell(self):
        even = self.ticked["even"]
        self.assertIsNotNone(even, "the book shows one row only")
        self._reaches(even["row"]["color"], even["last"], self.ticked)

    def test_under_the_pointer_the_last_cell_takes_the_rows_ground(self):
        self.assertTrue(self.hovered["hover"], self.hovered)
        first = self.hovered["first"]
        self._reaches(first["row"]["color"], first["last"], self.hovered)

    def test_what_scrolls_under_the_pinned_cell_reads_as_cut(self):
        """A figure half under the pinned column must not pass for a
        shorter figure: a hairline on the cell's left edge and a short
        shadow beside it say the column goes on."""
        edge = self.ticked["edge"]
        self.assertEqual(self.ticked["first"]["last"]["position"], "sticky",
                         self.ticked)
        self.assertIn("inset", edge["line"], edge)
        self.assertNotIn(edge["shade"]["content"], ("none", "normal"), edge)
        self.assertEqual(edge["shade"]["position"], "absolute", edge)
        self.assertIn("gradient", edge["shade"]["image"], edge)
        self.assertGreaterEqual(edge["shade"]["width"], 8, edge)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class PositionCardsMeasuredTests(TestCase):
    """/positions/' row of small cards: no card narrower than the board
    draws it while the column is wider than that, and its tables whole
    without a sideways scroll, at 1280, 1440 and 1920, rail shut and open.

    The desk v2 (S2.2, the board the operator approved on 2026-11-13:
    "amazing work, bravo, I need it fast!!") replaced the old row
    (direction, asset class, monthly realized P&L) with its lower row:
    closed in 24 h, the REAL exposure by class and by side, closed in 30
    days by world. The same measures stand, on that row; the floor is the
    board's own width for each card (the review of 2026-11-13: S0's 300 px
    came from the old asset-class card, and the board holds the exposure at
    248 px and the 30 days' table whole at 274)."""

    #: The board's width for each card of the row (Desk2.dc.html).
    FLOORS = (300, 248, 274)

    VIEWPORTS = ((1280, 800), (1440, 900), (1920, 1080))

    PROBE = r"""(async function () {
        function frame() {
            return new Promise(function (r) {
                requestAnimationFrame(function () { requestAnimationFrame(r); });
            });
        }
        function finish() {
            document.getAnimations().forEach(function (a) {
                try { a.finish(); } catch (e) {}
            });
        }
        var rail = document.querySelector(".signals-rail");
        var grid = document.querySelector(".pd-lower");
        var out = { width: window.innerWidth, states: {} };
        var states = ["closed", "open"];
        for (var i = 0; i < states.length; i++) {
            rail.classList.toggle("open", states[i] === "open");
            void getComputedStyle(rail).width;
            finish();
            await frame();
            finish();
            out.states[states[i]] = {
                grid: grid.getBoundingClientRect().width,
                cards: Array.prototype.map.call(grid.children, function (c) {
                    return c.getBoundingClientRect().width;
                }),
                tables: Array.prototype.map.call(
                    grid.querySelectorAll("table"), function (t) {
                        var w = t.parentElement;
                        return { head: t.querySelector("thead").textContent
                                         .replace(/\s+/g, " ").trim(),
                                 scrollWidth: Math.max(w.scrollWidth,
                                     Math.ceil(t.getBoundingClientRect().width)),
                                 clientWidth: w.clientWidth };
                    })
            };
        }
        return JSON.stringify(out);
    })()"""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s0_cards", password="x")
        _quote("BTCUSD", 60600)
        _trade(user)
        _legacy(user)
        # The lower row's three cards with something in each: a REAL
        # position for the exposure, a close in the last 24 hours.
        _trade(user, paper=False, qty="0.1")
        from bot_program.models import AssetBotTrade
        closed = _trade(user, status="CLOSED", qty="0.2")
        AssetBotTrade.objects.filter(pk=closed.pk).update(
            exit_price=Decimal("61200"), pnl=Decimal("240"),
            closed_at=timezone.now() - timedelta(hours=3))
        client = Client()
        client.force_login(user)
        page = _get(client, "/positions/")
        if 'aria-label="Closed in thirty days, by world"' not in page:
            raise AssertionError("/positions/ no longer shows the lower row "
                                 "this measures")
        cls.got = _measure({"/positions/": page}, cls.VIEWPORTS, cls.PROBE,
                           "sv-s0-cards-")

    def test_the_asset_class_table_is_there(self):
        # The lower row's tables (S2.2, 2026-11-13: "amazing work, bravo, I
        # need it fast!!"): the 24 h closes and the 30 days by world.
        for (url, width), got in sorted(self.got.items()):
            for state, row in sorted(got["states"].items()):
                with self.subTest(width=width, rail=state):
                    self.assertEqual(len(row["cards"]), 3, row)
                    heads = [t["head"].lower() for t in row["tables"]]
                    self.assertTrue(any("exit" in h for h in heads), row)
                    self.assertTrue(any("won" in h for h in heads), row)

    def test_no_card_is_squeezed_under_the_board_s_width(self):
        """Updated deliberately (the review of 2026-11-13, the board the
        operator approved: "amazing work, bravo, I need it fast!!"): each
        card's floor is the board's width for it, the 24 hours keeping S0's
        300; the tables stay whole (the test below)."""
        for (url, width), got in sorted(self.got.items()):
            for state, row in sorted(got["states"].items()):
                with self.subTest(width=width, rail=state):
                    for card, floor in zip(row["cards"], self.FLOORS):
                        self.assertGreaterEqual(
                            card, min(floor, row["grid"]) - 0.5,
                            "at %d px, rail %s: a card %.0f px wide" %
                            (width, state, card))

    def test_the_asset_class_table_needs_no_sideways_scroll(self):
        for (url, width), got in sorted(self.got.items()):
            for state, row in sorted(got["states"].items()):
                for table in row["tables"]:
                    with self.subTest(width=width, rail=state):
                        self.assertLessEqual(
                            table["scrollWidth"], table["clientWidth"] + 1,
                            "at %d px, rail %s: %d px of the table hidden"
                            % (width, state,
                               table["scrollWidth"] - table["clientWidth"]))


# ══════════════════════════════════════════════════════════════════════════
# 2. The ticket's face
# ══════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TicketFaceMeasuredTests(TestCase):
    """Every price and label on every ticket of the instrument page (the
    header's and the chart's compact one) computes to the mono token, the
    face the spread between them already wore."""

    PROBE = r"""(function () {
        function face(el) { return getComputedStyle(el).fontFamily; }
        function all(sel) {
            return Array.prototype.map.call(document.querySelectorAll(sel), face);
        }
        var token = document.createElement("span");
        token.style.fontFamily = "var(--font-mono)";
        document.querySelector(".sv-ticket").appendChild(token);
        return JSON.stringify({
            mono: face(token), body: face(document.body),
            prices: all(".sv-ticket .tk-px"),
            labels: all(".sv-ticket .tk-lbl"),
            spreads: all(".sv-ticket .tk-v")
        });
    })()"""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s0_ticket", password="x")
        _two_sided_quote("BTCUSD", "60590.5", "60610.5")
        client = Client()
        client.force_login(user)
        page = _get(client, "/instruments/BTCUSD/")
        cls.got = _measure({"/instruments/BTCUSD/": page}, ((1440, 900),),
                           cls.PROBE, "sv-s0-ticket-")[("/instruments/BTCUSD/", 1440)]

    def test_the_token_is_not_the_body_face(self):
        """The check below means nothing if the two faces are one."""
        self.assertIn("monospace", self.got["mono"])
        self.assertNotEqual(self.got["mono"], self.got["body"])

    def test_the_bid_and_the_ask_print_in_the_mono_face(self):
        self.assertGreaterEqual(len(self.got["prices"]), 2, self.got)
        for face in self.got["prices"]:
            self.assertEqual(face, self.got["mono"], self.got)

    def test_so_do_the_side_labels_and_the_spread(self):
        self.assertGreaterEqual(len(self.got["labels"]), 2, self.got)
        for face in self.got["labels"] + self.got["spreads"]:
            self.assertEqual(face, self.got["mono"], self.got)


# ══════════════════════════════════════════════════════════════════════════
# 3. /signals/ draws its charts
# ══════════════════════════════════════════════════════════════════════════

#: A stand-in for Chart.js: it counts its own runs and the charts asked of
#: it, and notes whether the theme's defaults were set before each chart.
STUB_CHART_JS = r"""(function (w) {
    w.__s0LibraryRuns = (w.__s0LibraryRuns || 0) + 1;
    function Chart(canvas, config) {
        this.canvas = canvas;
        this.config = config;
        this.themed = !!(Chart.defaults && Chart.defaults.color);
        Chart.instances.push(this);
    }
    Chart.prototype.destroy = function () { this.destroyed = true; };
    Chart.instances = [];
    Chart.defaults = { font: {} };
    w.Chart = Chart;
})(window);
"""


def _sri(source):
    return "sha384-" + base64.b64encode(
        hashlib.sha384(source.encode("utf-8")).digest()).decode("ascii")


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class SignalsChartMeasuredTests(TestCase):
    """/signals/ with its metrics fragment swapped in as htmx 1.9.10 swaps
    it: no error, every chart drawn into the canvas on the page and drawn
    in the theme's colours, the library fetched once though the fragment
    comes twice."""

    #: htmx 1.9.10's swap, as far as scripts go (htmx.js, insertNodesBefore,
    #: makeAjaxLoadTask, processScripts, evalScript): the response is
    #: parsed with its scripts inert, its nodes go into the target, and then
    #: each script is re-created, attributes and text copied, async false,
    #: inserted where the old one was. An inline script runs on insertion;
    #: a script with a src is fetched and runs later.
    PROBE = r"""(async function () {
        var FRAGMENT = %s;
        var errors = [];
        window.addEventListener("error", function (e) {
            errors.push(String(e.message || e.type));
        });
        var consoleError = console.error;
        console.error = function () {
            errors.push(Array.prototype.join.call(arguments, " "));
            return consoleError.apply(console, arguments);
        };
        function evalScript(script) {
            if (!(script.type === "text/javascript" || script.type === "module"
                  || script.type === "")) return;
            var fresh = document.createElement("script");
            Array.prototype.forEach.call(script.attributes, function (a) {
                fresh.setAttribute(a.name, a.value);
            });
            fresh.textContent = script.textContent;
            fresh.async = false;
            var parent = script.parentElement;
            try { parent.insertBefore(fresh, script); }
            finally { if (script.parentElement) script.parentElement.removeChild(script); }
        }
        function swap(target, html) {
            var tpl = document.createElement("template");
            tpl.innerHTML = html;
            var kids = Array.prototype.slice.call(tpl.content.childNodes);
            while (target.firstChild) target.removeChild(target.firstChild);
            kids.forEach(function (k) { target.appendChild(k); });
            kids.forEach(function (k) {
                if (k.nodeType !== 1) return;
                if (k.matches("script")) evalScript(k);
                Array.prototype.forEach.call(k.querySelectorAll("script"), evalScript);
            });
        }
        function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
        async function until(test, ms) {
            var t0 = Date.now();
            while (!test() && Date.now() - t0 < ms) await wait(20);
        }
        function drawn() {
            var C = window.Chart;
            return {
                library: typeof C === "function",
                made: C && C.instances ? C.instances.length : 0,
                live: C && C.instances ? C.instances.filter(function (c) {
                    return !c.destroyed;
                }).map(function (c) {
                    return { id: c.canvas && c.canvas.id,
                             onPage: !!(c.canvas && c.canvas.isConnected),
                             themed: c.themed };
                }) : []
            };
        }
        var target = document.querySelector(
            '.sv-metrics-wrapper[hx-get="/htmx/metrics/signals/"]');
        if (!target) return JSON.stringify({ noTarget: true });
        swap(target, FRAGMENT);
        await until(function () { return drawn().made >= 3; }, 4000);
        await wait(60);
        var first = drawn();
        swap(target, FRAGMENT);
        await until(function () { return drawn().made >= 6; }, 4000);
        await wait(60);
        return JSON.stringify({
            errors: errors, first: first, second: drawn(),
            libraryRuns: window.__s0LibraryRuns || 0
        });
    })()"""

    CHARTS = ["signals-daily-chart", "signals-r-hist", "signals-setup-chart"]

    @classmethod
    def setUpTestData(cls):
        from signals.models_smc import SmcSignal
        user = get_user_model().objects.create_user("s0_signals", password="x")
        now = timezone.now()
        for i, (setup, side) in enumerate((("OB_RETEST", "LONG"),
                                           ("FVG_TAP", "SHORT"),
                                           ("PO3", "LONG"))):
            SmcSignal.objects.create(
                symbol="BTCUSD", timeframe="1h", setup=setup, direction=side,
                headline="synthetic", thesis="synthetic", invalidation="none",
                entry=100.0, stop=99.0, target=102.0, conviction=60 + i,
                created_at=now - timedelta(hours=i + 1))
        client = Client()
        client.force_login(user)
        page = _get(client, "/signals/")
        fragment = _get(client, "/htmx/metrics/signals/")
        if CHART_JS not in fragment:
            raise AssertionError("the fragment no longer loads Chart.js from "
                                 + CHART_JS)
        fragment = fragment.replace(
            CHART_JS, "data:text/javascript;base64,"
            + base64.b64encode(STUB_CHART_JS.encode("utf-8")).decode("ascii"))
        fragment = re.sub(r"sha384-[A-Za-z0-9+/]{64}", _sri(STUB_CHART_JS),
                          fragment)
        cls.got = _measure({"/signals/": page}, ((1440, 900),),
                           cls.PROBE % json.dumps(fragment),
                           "sv-s0-signals-")[("/signals/", 1440)]

    def test_nothing_is_thrown_or_logged(self):
        self.assertNotIn("noTarget", self.got)
        self.assertEqual(self.got["errors"], [], self.got)

    def test_every_chart_is_drawn_on_the_page_in_the_themes_colours(self):
        for when in ("first", "second"):
            drawn = self.got[when]
            with self.subTest(swap=when):
                self.assertTrue(drawn["library"], self.got)
                self.assertEqual(sorted(c["id"] for c in drawn["live"]),
                                 self.CHARTS, self.got)
                for chart in drawn["live"]:
                    self.assertTrue(chart["onPage"], chart)
                    self.assertTrue(chart["themed"], chart)

    def test_the_library_is_fetched_once_per_page(self):
        """The fragment refreshes every minute; the guard keeps the second
        swap from bringing the library again."""
        self.assertEqual(self.got["libraryRuns"], 1, self.got)


class SignalsChartSourceTests(SimpleTestCase):
    """The same facts at the source, for a machine with no Chromium."""

    def test_the_loader_is_not_a_static_script_tag(self):
        """htmx brings a static <script src> back on every swap and runs
        what follows it before the library has arrived."""
        src = re.sub(r"\{% comment %\}.*?\{% endcomment %\}", "",
                     _read("templates", "_chart_assets.html"), flags=re.S)
        self.assertNotIn("<script src", src)
        self.assertIn("w.svChartJsReady = function (draw)", src)
        self.assertIn(CHART_JS, src)

    def test_the_signals_charts_wait_for_the_library(self):
        src = _read("templates", "dashboard", "_signals_metrics.html")
        block = re.findall(r"<script>(.*?)</script>", src, flags=re.S)[-1]
        code = re.sub(r"/\*.*?\*/", "", block, flags=re.S).strip()
        self.assertTrue(code.startswith("window.svChartJsReady(function"), code[:80])
        self.assertTrue(code.endswith("});"), code[-80:])
        self.assertEqual(code.count("new Chart("), 3)


# ══════════════════════════════════════════════════════════════════════════
# 4. The TradingView credit
# ══════════════════════════════════════════════════════════════════════════

class ChartCreditTests(TestCase):
    """lightweight-charts' licence: the NOTICE's attribution
    ("TradingView Lightweight Charts™ / Copyright (c) 2023 TradingView,
    Inc. https://www.tradingview.com/") and a link to tradingview.com, on
    the page, in the caption row under the chart, never hidden."""

    def _credit(self, markup):
        found = re.search(r'<div class="sv-chart-credit"[^>]*>(.*?)</div>',
                          markup, flags=re.S)
        self.assertIsNotNone(found, "no credit under the chart")
        return found

    def test_the_widget_carries_it_once(self):
        src = _read("templates", "_partials", "chart_widget.html")
        self.assertEqual(src.count(CREDIT_LINK), 1)
        credit = self._credit(src)
        self.assertNotIn("hidden", credit.group(0).split(">", 1)[0])
        self.assertIn(CREDIT_LINK, credit.group(1))
        words = " ".join(re.sub(r"<[^>]+>", " ", credit.group(1)).split())
        for part in ("Charts by TradingView", "TradingView Lightweight Charts™",
                     "Copyright (c) 2023 TradingView, Inc."):
            self.assertIn(part, words)

    def test_the_instrument_page_shows_it_once_under_its_chart(self):
        user = get_user_model().objects.create_user("s0_credit", password="x")
        _instrument("BTCUSD")
        client = Client()
        client.force_login(user)
        page = _get(client, "/instruments/BTCUSD/")
        self.assertEqual(page.count(CREDIT_LINK), 1)
        credit = self._credit(page)
        link = re.search(r"<a\b[^>]*%s[^>]*>" % re.escape(CREDIT_LINK),
                         credit.group(1)).group(0)
        self.assertIn('target="_blank"', link)
        self.assertIn('rel="noopener noreferrer"', link)
        # In the caption row: after the chart's captions, before the
        # library that draws it.
        self.assertGreater(credit.start(), page.index('class="sv-pos-legend"'))
        self.assertLess(credit.start(), page.index("lightweight-charts@4.1.0"))


# ══════════════════════════════════════════════════════════════════════════
# 5 and 6. The theme's own controls, and links
# ══════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class ThemeAndLinksMeasuredTests(TestCase):
    """On /positions/: the root and a native control compute the dark
    scheme, and the light one under body.light-mode (the class sits on
    <body>, the scrollbars follow the root). A link with no class of its
    own (placed in the page, as /orcs/ prints "Orc #13") reads in the text
    colour, underlined at 40 %, fully underlined under the pointer."""

    SCHEME_PROBE = r"""(function () {
        function scheme(el) { return getComputedStyle(el).colorScheme; }
        var select = document.createElement("select");
        document.querySelector(".page-content").appendChild(select);
        var out = { root: scheme(document.documentElement), control: scheme(select) };
        document.body.classList.add("light-mode");
        out.lightRoot = scheme(document.documentElement);
        out.lightControl = scheme(select);
        document.body.classList.remove("light-mode");
        out.backRoot = scheme(document.documentElement);
        return JSON.stringify(out);
    })()"""

    #: The page's entrance animations (the content fades and rises for
    #: 0.4 to 0.9 s) are finished first, or the stat strip under the link
    #: is still rising through the spot the pointer is sent to.
    LINK_PROBE = r"""(async function (phase) {
        function frame() {
            return new Promise(function (r) {
                requestAnimationFrame(function () { requestAnimationFrame(r); });
            });
        }
        function finish() {
            document.getAnimations().forEach(function (an) {
                try { an.finish(); } catch (e) {}
            });
        }
        function rgba(c) {
            var m = /^rgba?\(([^)]*)\)$/.exec(c), n;
            if (m) {
                n = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
                return [n[0], n[1], n[2], n.length > 3 ? n[3] : 1];
            }
            m = /^color\(srgb ([^)]*)\)$/.exec(c);
            if (m) {
                n = m[1].split(/[\s\/]+/).filter(Boolean).map(parseFloat);
                return [n[0] * 255, n[1] * 255, n[2] * 255, n.length > 3 ? n[3] : 1];
            }
            return c;
        }
        var a = document.getElementById("s0-orc-link");
        if (phase === "place") {
            finish();
            var line = document.createElement("p");
            a = document.createElement("a");
            a.id = "s0-orc-link";
            a.href = "#orc-13";
            a.textContent = "Orc #13";
            line.appendChild(a);
            var page = document.querySelector(".page-content");
            page.insertBefore(line, page.firstChild);
            window.scrollTo(0, 0);
            finish();
        }
        await frame();
        var ink = document.createElement("span");
        ink.style.color = "var(--text-primary)";
        document.body.appendChild(ink);
        var cs = getComputedStyle(a), r = a.getBoundingClientRect();
        var x = r.left + r.width / 2, y = r.top + r.height / 2;
        return JSON.stringify({
            x: x, y: y, onTop: document.elementFromPoint(x, y) === a,
            hover: a.matches(":hover"),
            text: rgba(getComputedStyle(ink).color),
            color: rgba(cs.color),
            line: cs.textDecorationLine,
            underline: rgba(cs.textDecorationColor)
        });
    })(%s)"""

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s0_theme", password="x")
        client = Client()
        client.force_login(user)
        markup = _get(client, "/positions/")
        tmp = tempfile.mkdtemp(prefix="sv-s0-theme-")
        try:
            path = pathlib.Path(tmp) / "positions.html"
            path.write_text(_offline(markup), encoding="utf-8")
            chrome = _Chrome(CHROME)
            try:
                sid = chrome.page(1440, 900, False)
                chrome.open(sid, path.as_uri())
                cls.scheme = json.loads(chrome.eval(sid, cls.SCHEME_PROBE))
                cls.rest = json.loads(chrome.eval(sid, cls.LINK_PROBE % '"place"'))
                chrome.call("Input.dispatchMouseEvent",
                            {"type": "mouseMoved", "x": cls.rest["x"],
                             "y": cls.rest["y"]}, session=sid)
                cls.hovered = json.loads(chrome.eval(sid, cls.LINK_PROBE % '"read"'))
            finally:
                chrome.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _same_ink(self, got, want, alpha):
        self.assertIsInstance(got, list, got)
        for a, b in zip(got[:3], want[:3]):
            self.assertAlmostEqual(a, b, delta=1.5, msg=(got, want))
        self.assertAlmostEqual(got[3], alpha, delta=0.02, msg=got)

    def test_the_dark_theme_asks_for_dark_controls(self):
        self.assertEqual(self.scheme["root"], "dark", self.scheme)
        self.assertEqual(self.scheme["control"], "dark", self.scheme)
        self.assertEqual(self.scheme["backRoot"], "dark", self.scheme)

    def test_light_mode_asks_for_light_ones(self):
        self.assertEqual(self.scheme["lightRoot"], "light", self.scheme)
        self.assertEqual(self.scheme["lightControl"], "light", self.scheme)

    def test_a_bare_link_reads_in_the_text_colour(self):
        self._same_ink(self.rest["color"], self.rest["text"], 1)
        self.assertIn("underline", self.rest["line"])
        self.assertFalse(self.rest["hover"])
        self._same_ink(self.rest["underline"], self.rest["text"], 0.4)

    def test_under_the_pointer_its_underline_is_full(self):
        # The pointer was sent to the link itself, nothing over it.
        self.assertTrue(self.rest["onTop"], self.rest)
        self.assertTrue(self.hovered["hover"], self.hovered)
        self._same_ink(self.hovered["color"], self.hovered["text"], 1)
        self._same_ink(self.hovered["underline"], self.hovered["text"], 1)
