"""ONE PRICE EVERYWHERE: every surface, one moment (2026-11-12).

The operator, 2026-11-12: "all the prices dont seem to be the same at the
same time at all between the different rendering sources, bottom
headband, the horde ... they need to be similar alltogether". Measured on
the synthetic fixture (scratchpad/onequote/measure_before.md, table A): a
held EURUSD printed 1.08447 on the Horde, 1.0845 on /positions/, 1.08390
on the headband, the rails, the hero, the card, the ticket and the hover,
1.08 on /instruments/; gold 2648.30 on the Horde, 2671.30 (Yahoo's future,
its previous close) on eight surfaces.

Here every surface is rendered by the test client at one held instant and
every price cell is collected by its attribute (data-q, data-q-f,
data-q-side), with every quote block the responses carry:

  * every cell's text is the rule's own text for its field and side
    (market_data.one_quote.Shown.field_text), so every cell of a symbol
    agrees with every other;
  * every quote block carries the rule's payload, as is;
  * the reference values land everywhere: EURUSD 1.08447, XAUUSD 2648.30,
    AAPL 228.27 (eToro's bid: the fixture's rows are longs), GBPUSD
    1.29410 (nobody holds it: its one LiveQuote row);
  * the Horde's mark is the /positions/ Current cell;
  * no template prints a price outside the rule (the stray-cell pin).

Synthetic fixture (tests/one_quote_fixture.py); no outside call (the Yahoo
and eToro clients are never reached: the pages read the database only).

Run with:  python manage.py test tests.test_one_quote_screens
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tests.one_quote_fixture import REFERENCE, T, seed_measured

HOST = "127.0.0.1"
SYMBOLS = ("EURUSD", "XAUUSD", "AAPL", "GBPUSD")


class _Cells(HTMLParser):
    """Every [data-q] element's attributes and text, and every quote block."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells, self.blocks = [], []
        self.stack = []          # [(tag, cell dict or None)]
        self.in_block = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and "data-sv-quotes" in a:
            self.in_block = []
            return
        if tag in self.VOID:
            return
        cell = None
        if "data-q" in a:
            cell = {"sym": a.get("data-q") or "", "f": a.get("data-q-f") or "price",
                    "side": a.get("data-q-side") or "", "text": [],
                    "attrs": a}
            self.cells.append(cell)
        self.stack.append((tag, cell))

    def handle_endtag(self, tag):
        if tag == "script" and self.in_block is not None:
            self.blocks.append(json.loads("".join(self.in_block)))
            self.in_block = None
            return
        while self.stack:
            t, _c = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if self.in_block is not None:
            self.in_block.append(data)
            return
        for _t, c in self.stack:
            if c is not None:
                c["text"].append(data)


def _parse(html):
    p = _Cells()
    p.feed(html)
    for c in p.cells:
        c["text"] = " ".join("".join(c["text"]).split())
    return p.cells, p.blocks


class _Screens(TestCase):
    """The fixture, the clock held at T, a signed-in operator."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "oq_screens", password="x", is_staff=True)
        self.rows = seed_measured(self.user)
        from instruments.models import Instrument
        Instrument.objects.filter(symbol__in=SYMBOLS).update(is_watchlist=True)
        for patch in (mock.patch("django.utils.timezone.now", return_value=T),
                      mock.patch("market_data.one_quote.now", return_value=T)):
            patch.start()
            self.addCleanup(patch.stop)
        self.client.force_login(self.user)

    def shown(self):
        from market_data.one_quote import shown_many
        return shown_many(list(SYMBOLS), user=self.user, now=T)

    def page(self, url):
        r = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200, url)
        return r.content.decode("utf-8")

    def json(self, url):
        r = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200, url)
        return r.json()

    def check_cells(self, url, html, *, expect=()):
        """Every cell of the page is the rule's text; returns the cells."""
        cells, blocks = _parse(html)
        want = self.shown()
        for c in cells:
            sym = c["sym"].upper()
            if sym not in want:
                continue
            exp = want[sym].field_text(c["f"], side=c["side"] or None,
                                       now_at=T)
            with self.subTest(url=url, sym=sym, field=c["f"], side=c["side"]):
                self.assertEqual(c["text"], exp, c["attrs"])
        for b in blocks:
            for sym, payload in b.get("q", {}).items():
                if sym in want:
                    with self.subTest(url=url, block=sym):
                        self.assertEqual(payload, want[sym].payload())
        for sym in expect:
            with self.subTest(url=url, present=sym):
                self.assertTrue(any(c["sym"].upper() == sym for c in cells),
                                f"{url} prints {sym} without a data-q cell")
        return cells, blocks

    def prices(self, cells, sym):
        """The compact and the positioned (long: bid) price texts of `sym`."""
        return [c["text"] for c in cells
                if c["sym"].upper() == sym and c["f"] == "price"]


class TheShellTests(_Screens):
    """The top quote band (cells and cards), the watchlist rail (cells and
    cards) and the bottom WATCHLIST rows: on every page."""

    def test_the_shell_agrees_with_the_rule(self):
        html = self.page("/positions/")
        cells, blocks = self.check_cells("/positions/", html,
                                         expect=("EURUSD", "XAUUSD", "GBPUSD", "AAPL"))
        self.assertTrue(blocks, "the page carries its quote block")
        for sym in SYMBOLS:
            texts = self.prices(cells, sym)
            self.assertTrue(texts, sym)
            self.assertEqual(set(texts), {REFERENCE[sym]}, (sym, texts))

    def test_the_headband_card_says_whose_and_how_old(self):
        html = self.page("/positions/")
        cells, _ = _parse(html)
        words = {c["text"] for c in cells
                 if c["sym"] == "EURUSD" and c["f"] == "words"}
        self.assertIn("eToro bid · 25 s", words)
        who = {c["text"] for c in cells if c["sym"] == "XAUUSD" and c["f"] == "who"}
        self.assertEqual(who, {"eToro"})
        chg = {c["text"] for c in cells if c["sym"] == "EURUSD" and c["f"] == "chg"}
        self.assertEqual(chg, {"—"}, "Yahoo's day change is not eToro's")

    def test_a_sparkline_is_keyed_apart_from_the_price_cells(self):
        """Measured on the scratch server (2026-11-12): a spark keyed by
        data-q was a price cell to the painter, which wrote the price over
        its svg. A spark says its symbol in data-q-spark and its bars' feed
        in data-q-fam, and never carries data-q."""
        from datetime import timedelta

        from django.core.cache import cache

        from tests.one_quote_fixture import daily_bar
        for days, close in ((2, "1.08300"), (1, "1.08480")):
            daily_bar("EURUSD", T - timedelta(days=days), close)
        cache.clear()
        html = self.page("/positions/")
        tags = re.findall(r"<(?:span|div)\b[^>]*\bdata-points=[^>]*>", html)
        eur = [t for t in tags if 'data-q-spark="EURUSD"' in t]
        self.assertGreaterEqual(len(eur), 2, tags)
        for t in tags:
            self.assertNotRegex(t, r"\sdata-q=", t)
        for t in eur:
            self.assertIn('data-q-fam="yahoo"', t)
            # eToro's price has no day change: the line is neither green
            # nor red (it was red, a fall nobody measured).
            self.assertIn('data-up=""', t)


class ThePositionPagesTests(_Screens):

    def test_positions_and_portfolio_current(self):
        for url in ("/positions/", "/positions/live/", "/portfolio/",
                    "/portfolio/live/"):
            html = self.page(url)
            cells, _ = self.check_cells(url, html)
            for sym in ("EURUSD", "XAUUSD", "AAPL"):
                cur = [c for c in cells if c["sym"] == sym
                       and c["side"] == "bid" and c["f"] == "price"]
                self.assertTrue(cur, (url, sym))
                self.assertEqual({c["text"] for c in cur}, {REFERENCE[sym]},
                                 (url, sym))

    def test_command_portfolio_tab(self):
        html = self.page("/command/tab/portfolio/")
        cells, blocks = self.check_cells("/command/tab/portfolio/", html,
                                         expect=("EURUSD", "XAUUSD", "AAPL"))
        self.assertTrue(blocks, "a fragment fetched alone carries its block")
        for sym in ("EURUSD", "XAUUSD", "AAPL"):
            self.assertIn(REFERENCE[sym], self.prices(cells, sym))

    def test_the_horde_is_the_current_cell(self):
        board = self.json("/api/horde/")
        seats = [s for g in board["groups"] for s in g["seats"]]
        marks = {s["symbol"]: s["mark"] for s in seats}
        want = self.shown()
        for sym in ("EURUSD", "XAUUSD", "AAPL"):
            self.assertEqual(marks[sym]["t"], REFERENCE[sym], sym)
            self.assertEqual(marks[sym]["word"],
                             want[sym].words(T, side="bid"), sym)
            self.assertEqual(marks[sym]["q"], {"s": sym, "side": "bid"})
        self.assertEqual(board["quotes"]["q"]["EURUSD"],
                         want["EURUSD"].payload())


class TheInstrumentPageTests(_Screens):

    def test_hero_card_and_tickets(self):
        for sym in SYMBOLS:
            url = f"/instruments/{sym}/"
            html = self.page(url)
            cells, _ = self.check_cells(url, html, expect=(sym,))
            here = [c for c in cells if c["sym"] == sym]
            fields = {c["f"] for c in here}
            for f in ("price", "words", "chg", "sides", "who", "age"):
                self.assertIn(f, fields, (sym, f))
            self.assertIn(REFERENCE[sym], self.prices(cells, sym))

    def test_the_held_ticket_trades_on_etoros_sides(self):
        html = self.page("/instruments/EURUSD/")
        cells, _ = _parse(html)
        bids = {c["text"] for c in cells if c["sym"] == "EURUSD" and c["f"] == "bid"}
        asks = {c["text"] for c in cells if c["sym"] == "EURUSD" and c["f"] == "ask"}
        self.assertEqual((bids, asks), ({"1.08447"}, {"1.08457"}))

    def test_the_outside_quote_is_only_the_slot(self):
        html = self.page("/instruments/XAUUSD/")
        cells, _ = _parse(html)
        slot = [c["text"] for c in cells if c["sym"] == "XAUUSD" and c["f"] == "slot"]
        self.assertEqual(len(slot), 1)
        self.assertTrue(slot[0].startswith(
            "Yahoo GC=F, the front-month future 2671.30 · "), slot)
        self.assertNotIn("2671.30", self.prices(cells, "XAUUSD"))

    def test_the_preview_api_is_the_rule(self):
        want = self.shown()
        for sym in SYMBOLS:
            d = self.json(f"/api/instrument-preview/{sym}/")
            self.assertEqual(d["price"], REFERENCE[sym], sym)
            self.assertEqual(d["q"], want[sym].payload(), sym)

    def test_the_chart_data_carries_now(self):
        want = self.shown()
        for sym in ("EURUSD", "GBPUSD"):
            d = self.json(f"/api/chart-data/?symbol={sym}&timeframe=1h")
            self.assertEqual(d["now"], want[sym].payload(), sym)
            self.assertIn("close_side", d["source"])


class TheOtherListsTests(_Screens):

    def test_instruments_list(self):
        html = self.page("/instruments/")
        cells, _ = self.check_cells("/instruments/", html,
                                    expect=("EURUSD", "XAUUSD", "AAPL", "GBPUSD"))
        for sym in SYMBOLS:
            self.assertIn(REFERENCE[sym], self.prices(cells, sym))

    def test_signal_rail_popups(self):
        from signals.models import Signal
        from instruments.models import Instrument
        from decimal import Decimal
        levels = {"EURUSD": ("bullish", "1.08400", "1.08000", "1.09200"),
                  "XAUUSD": ("bullish", "2660.00", "2630.00", "2720.00"),
                  "AAPL": ("bullish", "227.50", "222.00", "238.00"),
                  "GBPUSD": ("bearish", "1.29450", "1.29900", "1.28500")}
        for sym, (direction, entry, stop, target) in levels.items():
            Signal.objects.create(
                instrument=Instrument.objects.get(symbol=sym),
                signal_type="technical", direction=direction, urgency="medium",
                title=f"{sym} fixture signal", description="fixture",
                rule_name="ema_cross", score=0.72, sub_scores={},
                price_at_signal=Decimal(entry), suggested_entry=Decimal(entry),
                suggested_stop=Decimal(stop), suggested_target=Decimal(target),
                risk_reward_ratio=2.0, is_active=True)
        html = self.page("/partials/signal-rail/")
        cells, blocks = self.check_cells("/partials/signal-rail/", html,
                                         expect=SYMBOLS)
        self.assertTrue(blocks)
        for sym in SYMBOLS:
            self.assertIn(REFERENCE[sym], self.prices(cells, sym))


TEMPLATES = Path(settings.BASE_DIR) / "templates"
STRAY = re.compile(r"live_quote\.last|quote\.last\|floatformat|"
                   r"current_price\|floatformat|\.last\|floatformat|"
                   r"\b(?:w|item|m)\.(?:bid|ask)\|floatformat")


class NoStrayPriceCellTests(SimpleTestCase):
    """No template prints an instrument's price outside the rule's cells:
    a later page cannot bring back a second rule by a filter."""

    def test_no_template_formats_a_quote_itself(self):
        hits = []
        for path in TEMPLATES.rglob("*.html"):
            if path.name == "chart_widget.html":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8")
                                     .splitlines(), 1):
                if STRAY.search(line):
                    hits.append(f"{path.relative_to(TEMPLATES)}:{n}")
        self.assertEqual(hits, [])
