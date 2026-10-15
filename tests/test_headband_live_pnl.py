"""THE LIVE P&L ON THE PORTFOLIO CELL (2026-10-14).

The operator: "Add also on portfolio the live P&L please." The cockpit
strip's PORTFOLIO cell printed VALUE and "N pos · X% in"; the open P&L and
the open R were inside the hover dropdown, and both counted BOTH books —
real money at eToro added to the paper bots' simulator. There was no figure
anywhere in the band for the real book alone.

What is asserted here:
  - the cell carries a LIVE line without hovering: the open P&L of the
    REAL-MONEY rows alone, in money and in R, marked with the band's own
    venue idiom (sv-venue on the label, never on the value);
  - the paper book's figure is printed APART under its own PAPER marker, a
    demo row under DEMO, and no figure on the line ever adds two worlds;
  - a real row's P&L is the one bot_program.venue_mark.resolve priced
    (portfolio.services._trade_to_position) — the band re-sums those per-row
    figures by world (dashboard.position_summary.open_by_world) and never
    values a row a second time;
  - the world of a bot row is read from the trade itself (world_of), so a
    demo eToro fill is DEMO and no longer paints the dropdown row red;
  - a dash means NOT MEASURED: real rows open and none marked at the
    venue's rate, or no real row at all — each with its own title, never a
    "+0.00";
  - the figure says what it covers (2026-10-15, review): "· 1/2" when a
    real row is open and unmarked, "· stale" when one rests on the venue's
    last print, a manual Position that states no venue counted beside the
    worlds — on the strip and on the Portfolio page, in the same words;
  - up/down tone and the titles sit on children of the region, never on the
    region element (the refresher copies innerHTML, not attributes);
  - the dropdown is unchanged: OPEN P&L and OPEN R there are still both
    books, and VALUE still agrees with the cell;
  - the line is a data-sv-live region, refreshed by the one refresher;
  - the Portfolio page's head carries the same figure under the same words,
    with the same R (summed unrounded), on a sub-line that wraps rather
    than cutting the paper and demo figures off.

Run with:  python manage.py test tests.test_headband_live_pnl
"""
import html
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_headband_truth import (
    DASH, HOST, LIVE_SOURCE, _components, _config, _ctx, _position, _quote,
    _tick, _trade, _user, cell, dd_value, regions,
)
from tests.test_portfolio_live import cells as pf_cells

ETORO_LIVE = {"broker": "etoro", "broker_env": "live"}
ETORO_DEMO = {"broker": "etoro", "broker_env": "paper"}
PNL_REGION = "hb-pf-pnl"


# ── Fixtures ─────────────────────────────────────────────────────────────

def _real(user, symbol="BTCUSD", price="110", entry="100", stop=None,
          qty="1", env="live", stamp=True, hours_ago=None):
    """A REAL eToro row (paper=False, broker stamps), marked at the venue's
    own rate through venue_mark.stamp — the PR53 path — unless `stamp` is
    off, in which case the row carries no venue print at all. `hours_ago`
    dates the print: with no platform quote on the symbol, resolve then
    values the row at the venue's LAST print (VENUE_STALE), its age said."""
    from bot_program import venue_mark
    cfg = _config(user, name=f"{env}-{symbol}", mode="live")
    meta = dict(ETORO_LIVE if env == "live" else ETORO_DEMO)
    kw = {"paper": False, "metadata": meta, "config": cfg}
    if stop is not None:
        kw["stop_loss"] = Decimal(str(stop))
    trade = _trade(user, symbol, qty=qty, entry=entry, **kw)
    if stamp:
        at = (None if hours_ago is None
              else timezone.now() - timedelta(hours=hours_ago))
        assert venue_mark.stamp(trade, Decimal(str(price)), source="etoro",
                                via="tick", at=at)
    return trade


def _page(client, url=LIVE_SOURCE):
    return client.get(url, HTTP_HOST=HOST).content.decode()


def _span(body, name):
    """The inner HTML of the region span named `name`, exactly to its
    closing tag — test_headband_pnl_and_beat._region reads a 6000-char
    window, which here would run into the dropdown's both-books figure."""
    m = re.search(r'data-sv-live="%s"[^>]*>' % re.escape(name), body)
    assert m, name
    window = body[m.end():m.end() + 6000]
    depth, i = 1, 0
    while i < len(window) and depth:
        if window.startswith("<span", i):
            depth += 1
        elif window.startswith("</span>", i):
            depth -= 1
            if not depth:
                break
        i += 1
    return window[:i]


def _words(body, name):
    """The region's text with its whitespace folded, so "LIVE +10.00" is
    one spelling whatever the markup put between the two."""
    return " ".join(
        html.unescape(re.sub(r"<[^>]+>", " ", _span(body, name))).split())


def _titles(fragment):
    return [html.unescape(t) for t in re.findall(r'title="([^"]*)"',
                                                 fragment)]


def _title_of(fragment, text):
    """The title on the span whose own text is `text` ("" for none)."""
    m = re.search(r'<span([^>]*)>%s</span>' % re.escape(text), fragment)
    assert m, text
    t = re.search(r'title="([^"]*)"', m.group(1))
    return html.unescape(t.group(1)) if t else ""


def _opening_tag(body, name):
    m = re.search(r'<span[^>]*data-sv-live="%s"[^>]*>' % re.escape(name),
                  body)
    assert m, name
    return m.group(0)


def _pf_live_title(body):
    m = re.search(
        r'<div class="oc-strip-cell" title="([^"]*)">\s*<span '
        r'class="oc-strip-label"><span class="sv-venue sv-venue--live">'
        r'LIVE</span> OPEN P&amp;L', body)
    assert m, "LIVE OPEN P&L cell"
    return html.unescape(m.group(1))


def _sheet(name="sauron.css"):
    return (Path(settings.BASE_DIR) / "static" / "css" / name
            ).read_text(encoding="utf-8")


def _rule(css, selector):
    """The body of the rule whose selector list is exactly `selector`."""
    m = re.search(r"(?:^|[}\s])%s\s*\{([^}]*)\}" % re.escape(selector), css)
    assert m, selector
    return m.group(1)


# ── 1. The live figure: real money alone, in money and in R ──────────────

class TheLiveFigureTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_live")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def test_the_live_pnl_is_the_real_book_alone(self):
        _real(self.user, price="110", entry="100")          # +10 real
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")   # +30 paper
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_pnl_live"], 10.0)
        self.assertEqual(ctx["panel_open_pnl_live_display"], "+10.00")
        self.assertEqual(ctx["panel_live_positions"], 1)
        self.assertEqual(ctx["panel_live_positions_marked"], 1)
        # The both-books figure the dropdown prints is untouched.
        self.assertEqual(ctx["panel_open_pnl"], 40.0)
        self.assertEqual(ctx["panel_open_pnl_display"], "+40.00")

    def test_the_cell_prints_it_without_a_hover(self):
        _real(self.user, price="110", entry="100")
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")
        body = _page(self.client)
        self.assertTrue(_words(body, PNL_REGION).startswith("LIVE +10.00"),
                        _words(body, PNL_REGION))

    def test_the_live_r_counts_only_the_real_rows(self):
        _real(self.user, price="110", entry="100", stop="95")  # +2R real
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="1", entry="100",
               stop_loss=Decimal("90"))                        # +1R paper
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_r_live_display"], "+2.00R")
        self.assertEqual(ctx["panel_open_r_live"], 2.0)
        self.assertEqual(ctx["panel_open_r_live_n"], 1)
        # Both books' R stays what it was: 2 + 1.
        self.assertEqual(ctx["panel_open_r_display"], "+3.00R")
        self.assertEqual(ctx["panel_open_r_n"], 2)
        body = _page(self.client)
        self.assertIn("+2.00R", _span(body, PNL_REGION))
        self.assertNotIn("+3.00R", _span(body, PNL_REGION))

    def test_a_real_row_with_no_opening_stop_dashes_its_r(self):
        _real(self.user, price="110", entry="100")
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_pnl_live_display"], "+10.00")
        self.assertIsNone(ctx["panel_open_r_live_display"])
        self.assertEqual(ctx["panel_open_r_live_n"], 0)
        span = _span(_page(self.client), PNL_REGION)
        self.assertIn("+10.00", span)
        self.assertNotIn("0.00R", span)
        self.assertIn("R needs an entry, the opening stop and a venue mark",
                      span)

    def test_the_marker_is_the_bands_venue_idiom_on_the_label(self):
        _real(self.user)
        span = _span(_page(self.client), PNL_REGION)
        self.assertIn('class="sv-venue sv-venue--live"', span)
        self.assertIn(">LIVE</span>", span)
        # Not on the value: the figure keeps its own up/down colour.
        self.assertNotRegex(span, r'class="(up|down) sv-venue')
        self.assertNotRegex(span, r'class="sv-venue[^"]*"[^>]*>[+\-]\d')

    def test_the_real_figure_is_the_venue_marked_one_not_the_feed(self):
        """A real row priced by venue_mark.resolve at its venue's print:
        the feed's quote on the same symbol is not what the cell shows."""
        _real(self.user, price="104", entry="100")   # venue says 104
        _quote("BTCUSD", "110")                      # the feed says 110
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_pnl_live_display"], "+4.00")
        self.assertEqual(ctx["panel_open_pnl_live"],
                         ctx["panel_open_rows"][0]["pnl"])


# ── 2. Paper and demo apart, never added ─────────────────────────────────

class ApartNeverAddedTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_apart")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def test_the_paper_figure_is_printed_apart_under_its_own_marker(self):
        _real(self.user, price="110", entry="100")          # +10
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")   # +30
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_pnl_paper"], 30.0)
        self.assertEqual(ctx["panel_open_pnl_paper_display"], "+30.00")
        self.assertEqual(ctx["panel_paper_positions"], 1)
        span = _span(_page(self.client), PNL_REGION)
        self.assertIn('class="sv-venue sv-venue--paper">PAPER</span>', span)
        self.assertIn("+30.00", span)
        self.assertIn("+10.00", span)
        # The sum of the two worlds appears nowhere on the line.
        self.assertNotIn("+40.00", span)
        self.assertNotIn("40.00", span)

    def test_no_figure_on_the_line_is_a_sum_of_worlds(self):
        """Live +10, paper +30, demo +4 and a manual Position +40 that
        states no venue: the line prints the three worlds' own figures and
        none of the eleven sums of two or more of the four."""
        _real(self.user, price="110", entry="100")                  # +10
        _real(self.user, symbol="ETHUSD", price="104", entry="100",
              env="demo")                                           # +4
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")           # +30
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL", qty="2", entry="100")          # +40
        body = _page(self.client)
        words = _words(body, PNL_REGION)
        self.assertTrue(words.startswith("LIVE +10.00"), words)
        self.assertIn("PAPER +30.00", words)
        self.assertIn("DEMO +4.00", words)
        figures = set(re.findall(r"[+\-][\d,]+\.\d\d", words))
        self.assertEqual(figures, {"+10.00", "+30.00", "+4.00"}, words)
        # The dropdown still carries both books, legacy row included.
        self.assertEqual(dd_value(body, "OPEN P&L"), "+84.00")

    def test_a_demo_row_is_demo_not_live(self):
        """An eToro demo fill is paper=False with broker_env "paper": it
        is simulated money, never the real book and never folded into the
        platform's paper simulator either."""
        _real(self.user, price="110", entry="100", env="demo")
        ctx = _ctx(self.user)
        self.assertIsNone(ctx["panel_open_pnl_live"])
        self.assertEqual(ctx["panel_live_positions"], 0)
        self.assertEqual(ctx["panel_open_pnl_demo"], 10.0)
        self.assertEqual(ctx["panel_open_pnl_demo_display"], "+10.00")
        self.assertEqual(ctx["panel_demo_positions"], 1)
        self.assertIsNone(ctx["panel_open_pnl_paper"])
        self.assertEqual(ctx["panel_paper_positions"], 0)
        body = _page(self.client)
        span = _span(body, PNL_REGION)
        self.assertIn('class="sv-venue sv-venue--demo">DEMO</span>', span)
        self.assertIn("+10.00", span)
        # LIVE prints the dash for "no real-money position open".
        self.assertTrue(_words(body, PNL_REGION).startswith(f"LIVE {DASH}"),
                        _words(body, PNL_REGION))
        self.assertIn('title="No real-money position open"', span)

    def test_the_dropdown_row_of_a_demo_fill_loses_its_red_edge(self):
        """The row's world now comes from the trade itself (world_of), not
        from a unified row that has no metadata to read broker_env off —
        the only change to the dropdown, and a correction."""
        _real(self.user, env="demo")
        body = _page(self.client)
        rows = re.findall(r'<div class="ip-pos ip-pos--long[^"]*">', body)
        self.assertEqual(len(rows), 1, rows)
        self.assertNotIn("sv-row--live", rows[0])
        self.assertEqual(_ctx(self.user)["panel_open_rows"][0]["world"],
                         "demo")

    def test_a_real_fill_keeps_its_red_edge_in_the_dropdown(self):
        _real(self.user, env="live")
        body = _page(self.client)
        rows = re.findall(r'<div class="ip-pos ip-pos--long[^"]*">', body)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("sv-row--live", rows[0])
        self.assertEqual(_ctx(self.user)["panel_open_rows"][0]["world"],
                         "live")

    def test_a_legacy_position_is_in_no_world_and_still_in_both_books(self):
        """A manual Position states no venue: its P&L is in VALUE and the
        dropdown, in none of the three worlds — and the line COUNTS it
        (2026-10-15, review) rather than letting it vanish, so "no
        real-money position open" never stands silently over it."""
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL", qty="2", entry="100")     # +40
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_pnl"], 40.0)
        self.assertEqual(ctx["panel_unvenued_positions"], 1)
        self.assertEqual(ctx["panel_live_positions"], 0)
        self.assertEqual(ctx["panel_paper_positions"], 0)
        self.assertEqual(ctx["panel_demo_positions"], 0)
        self.assertIsNone(ctx["panel_open_pnl_live_display"])
        self.assertEqual(ctx["panel_open_rows"][0]["world"], "")
        body = _page(self.client)
        span, words = _span(body, PNL_REGION), _words(body, PNL_REGION)
        self.assertEqual(words, f"LIVE {DASH} 1 manual")
        self.assertNotIn("40.00", span)
        manual = _title_of(span, "1 manual")
        self.assertIn("1 manual position states no venue", manual)
        self.assertIn("in none of LIVE, PAPER or DEMO", manual)
        self.assertEqual(_title_of(span, "&mdash;"),
                         "No real-money position open; 1 manual position "
                         "states no venue")

    def test_no_paper_or_demo_marker_when_none_is_open(self):
        _real(self.user)
        span = _span(_page(self.client), PNL_REGION)
        self.assertNotIn("sv-venue--paper", span)
        self.assertNotIn("sv-venue--demo", span)
        self.assertNotIn("manual", span)

    def test_the_split_helper_never_adds_worlds_and_never_zeroes(self):
        from dashboard.position_summary import open_by_world
        got = open_by_world([
            {"world": "live", "pnl": 10.0, "r": 2.0},
            {"world": "live", "pnl": None, "r": None},
            {"world": "paper", "pnl": 30.0, "r": None},
            {"world": "demo", "pnl": -5.0, "r": -0.5},
            {"world": "", "pnl": 40.0, "r": 1.0},
            {"world": "shadow", "pnl": 1.0, "r": None},
        ])
        self.assertEqual(got["live"], {"n": 2, "n_marked": 1, "pnl": 10.0,
                                       "r": 2.0, "r_n": 1, "n_stale": 0,
                                       "stale_age_s": None})
        self.assertEqual(got["paper"], {"n": 1, "n_marked": 1, "pnl": 30.0,
                                        "r": None, "r_n": 0, "n_stale": 0,
                                        "stale_age_s": None})
        self.assertEqual(got["demo"], {"n": 1, "n_marked": 1, "pnl": -5.0,
                                       "r": -0.5, "r_n": 1, "n_stale": 0,
                                       "stale_age_s": None})
        # An unknown world is "no venue stated", beside the legacy rows.
        self.assertEqual(got[""]["n"], 2)
        self.assertEqual(got[""]["pnl"], 41.0)
        empty = open_by_world([])
        for world in ("live", "paper", "demo", ""):
            self.assertEqual(empty[world], {"n": 0, "n_marked": 0,
                                            "pnl": None, "r": None, "r_n": 0,
                                            "n_stale": 0,
                                            "stale_age_s": None})
        # Open and unmarked: None, never 0.0.
        unmarked = open_by_world([{"world": "live", "pnl": None, "r": None}])
        self.assertEqual(unmarked["live"]["n"], 1)
        self.assertIsNone(unmarked["live"]["pnl"])


# ── 3. The dash means not measured ───────────────────────────────────────

class DashNotZeroTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_dash")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def test_a_real_row_awaiting_its_venue_dashes_and_says_why(self):
        """A real gold row with only the platform's GC=F stand-in quote and
        no venue print: venue_mark.resolve says AWAITING_VENUE, no price —
        the basis between spot and the future is never a P&L."""
        _quote("XAUUSD", "2668", asset_class="commodity")
        _real(self.user, symbol="XAUUSD", entry="2650", stamp=False)
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_live_positions"], 1)
        self.assertEqual(ctx["panel_live_positions_marked"], 0)
        self.assertIsNone(ctx["panel_open_pnl_live"])
        self.assertIsNone(ctx["panel_open_pnl_live_display"])
        self.assertEqual(ctx["panel_open_rows"][0]["source"], "bot")
        body = _page(self.client)
        span = _span(body, PNL_REGION)
        self.assertIn("sv-unknown", span)
        self.assertIn("none could be marked at the venue", span)
        self.assertNotIn("+0.00", span)
        self.assertNotIn("+18.00", span)
        self.assertTrue(_words(body, PNL_REGION).startswith(f"LIVE {DASH}"),
                        _words(body, PNL_REGION))
        # Nothing measured: no coverage note on a dash.
        self.assertNotIn("ip-pnl-note", span)

    def test_an_empty_book_dashes_with_its_own_title(self):
        body = _page(self.client)
        span = _span(body, PNL_REGION)
        self.assertIn('title="No real-money position open"', span)
        self.assertIn("sv-unknown", span)
        self.assertNotIn("0.00", span)
        self.assertNotIn("sv-venue--paper", span)
        self.assertNotIn("sv-venue--demo", span)
        ctx = _ctx(self.user)
        self.assertIsNone(ctx["panel_open_pnl_live_display"])
        self.assertEqual(ctx["panel_live_positions"], 0)

    def test_a_paper_row_with_no_quote_dashes_the_paper_figure(self):
        _trade(self.user, "NOQUOTE")
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_paper_positions"], 1)
        self.assertIsNone(ctx["panel_open_pnl_paper_display"])
        span = _span(_page(self.client), PNL_REGION)
        self.assertIn('class="sv-venue sv-venue--paper">PAPER</span>', span)
        self.assertIn("Paper positions open, none with a live quote", span)
        self.assertNotIn("0.00", span)

    def test_the_defaults_before_any_book_is_read(self):
        """An anonymous render carries every key, as None or 0 — never a
        missing name that renders as an empty string."""
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        from core.context_processors import sauron_context
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        ctx = sauron_context(request)
        for key in ("panel_open_pnl_live", "panel_open_pnl_live_display",
                    "panel_open_r_live", "panel_open_r_live_display",
                    "panel_open_pnl_paper", "panel_open_pnl_paper_display",
                    "panel_open_r_paper", "panel_open_r_paper_display",
                    "panel_open_pnl_demo", "panel_open_pnl_demo_display"):
            self.assertIn(key, ctx, key)
            self.assertIsNone(ctx[key], key)
        for key in ("panel_open_r_live_n", "panel_live_positions",
                    "panel_live_positions_marked", "panel_open_r_paper_n",
                    "panel_paper_positions", "panel_paper_positions_marked",
                    "panel_demo_positions", "panel_unvenued_positions",
                    "panel_live_positions_stale"):
            self.assertEqual(ctx.get(key), 0, key)
        for key in ("panel_live_coverage_short", "panel_live_coverage_title",
                    "panel_live_stale_title", "panel_live_pnl_title",
                    "panel_live_r_title", "panel_unvenued_words",
                    "panel_unvenued_title"):
            self.assertEqual(ctx.get(key), "", key)
        self.assertEqual(ctx["panel_live_dash_title"],
                         "No real-money position open")


# ── 4. What the figure covers, said on the line ──────────────────────────

class WhatTheFigureCoversTests(TestCase):
    """2026-10-15, review. A figure labelled LIVE that covers one of two
    real rows, or rests on a venue print hours old, reads as the whole real
    book marked now. The line says both, readable without a hover, with
    the sentence as a title on the figure itself."""

    def setUp(self):
        self.user = _user("hbl_cover")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def _partial(self):
        _real(self.user, price="110", entry="100", stop="95")   # +10, +2R
        _quote("XAUUSD", "2668", asset_class="commodity")
        _real(self.user, symbol="XAUUSD", entry="2650", stamp=False)

    def test_a_partly_marked_real_book_says_so_on_the_line(self):
        self._partial()
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_live_positions"], 2)
        self.assertEqual(ctx["panel_live_positions_marked"], 1)
        self.assertEqual(ctx["panel_live_coverage_short"], "1/2")
        body = _page(self.client)
        span = _span(body, PNL_REGION)
        self.assertEqual(_words(body, PNL_REGION), "LIVE +10.00 +2.00R · 1/2")
        coverage = ("Across 1 of 2 real-money positions: the other could "
                    "not be marked at the venue's rate and is not in this "
                    "figure.")
        self.assertEqual(_title_of(span, "+10.00"), coverage)
        self.assertEqual(_title_of(span, "&middot; 1/2"), coverage)
        self.assertEqual(
            _title_of(span, "+2.00R"),
            "Across 1 of 2 real-money positions. R needs an entry, the "
            "opening stop and a venue mark")

    def test_a_wholly_marked_real_book_carries_no_note(self):
        _real(self.user, price="110", entry="100", stop="95")
        _real(self.user, symbol="ETHUSD", price="105", entry="100", stop="95")
        body = _page(self.client)
        span = _span(body, PNL_REGION)
        self.assertEqual(_words(body, PNL_REGION), "LIVE +15.00 +3.00R")
        self.assertNotIn("ip-pnl-note", span)
        self.assertEqual(_title_of(span, "+15.00"), "")
        self.assertEqual(_title_of(span, "+3.00R"), "")

    def test_a_stale_venue_print_is_said_on_the_line(self):
        """A real row whose newest venue print is three hours old and whose
        symbol has no platform quote: resolve values it at that print,
        VENUE_STALE — the line says "stale" and the age, never LIVE alone."""
        _real(self.user, price="110", entry="100", stop="95", hours_ago=3)
        rows = _ctx(self.user)["panel_open_rows"]
        self.assertEqual(rows[0]["pnl"], 10.0)
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_live_positions_stale"], 1)
        body = _page(self.client)
        span = _span(body, PNL_REGION)
        self.assertEqual(_words(body, PNL_REGION),
                         "LIVE +10.00 +2.00R · stale")
        stale = ("The real-money position rests on the venue's last print, "
                 "3 h old: nothing newer has come in from the venue, which "
                 "is normal while its market is shut.")
        self.assertEqual(_title_of(span, "+10.00"), stale)
        self.assertEqual(_title_of(span, "&middot; stale"), stale)

    def test_one_stale_row_of_two_names_the_oldest_print(self):
        _real(self.user, price="110", entry="100", hours_ago=5)
        _real(self.user, symbol="ETHUSD", price="105", entry="100")
        words = _words(_page(self.client), PNL_REGION)
        self.assertTrue(words.startswith("LIVE +15.00"), words)
        self.assertIn("· stale", words)
        self.assertIn("1 of 2 real-money positions rests on the venue's last "
                      "print, 5 h old",
                      _ctx(self.user)["panel_live_stale_title"])

    def test_a_fresh_venue_print_is_not_called_stale(self):
        _real(self.user, price="110", entry="100", stop="95")
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_live_positions_stale"], 0)
        self.assertNotIn("stale", _words(_page(self.client), PNL_REGION))

    def test_the_split_counts_a_stale_row_only_inside_the_figure(self):
        from dashboard.position_summary import open_by_world
        got = open_by_world([
            {"world": "live", "pnl": 10.0, "r": None,
             "mark_source": "venue_stale", "mark_age_s": 7200},
            {"world": "live", "pnl": 5.0, "r": None,
             "mark_source": "venue_stale", "mark_age_s": 18000},
            {"world": "live", "pnl": 1.0, "r": None, "mark_source": "venue",
             "mark_age_s": 30},
            # Not in the figure: an awaiting row is not "stale", it is out.
            {"world": "live", "pnl": None, "r": None,
             "mark_source": "awaiting_venue", "mark_age_s": 999999},
        ])["live"]
        self.assertEqual((got["n"], got["n_marked"], got["n_stale"]),
                         (4, 3, 2))
        self.assertEqual(got["stale_age_s"], 18000)
        self.assertEqual(got["pnl"], 16.0)


# ── 5. Colour on children, never on the region ───────────────────────────

class ToneTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_tone")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def test_a_gain_is_up_and_a_loss_is_down_on_a_child(self):
        _real(self.user, price="110", entry="100", stop="95")
        span = _span(_page(self.client), PNL_REGION)
        self.assertIn('<span class="up">+10.00</span>', span)
        self.assertIn('<span class="up">+2.00R</span>', span)

    def test_a_loss_is_down(self):
        _real(self.user, price="90", entry="100", stop="95")
        span = _span(_page(self.client), PNL_REGION)
        self.assertIn('<span class="down">-10.00</span>', span)
        self.assertIn('<span class="down">-2.00R</span>', span)

    def test_the_region_element_carries_no_tone_and_no_title(self):
        """The refresher swaps innerHTML and not attributes: a class or a
        title on the region itself would freeze at its first value."""
        _real(self.user, price="110", entry="100")
        tag = _opening_tag(_page(self.client), PNL_REGION)
        self.assertEqual(
            tag, '<span class="ip-pnl" data-sv-live="hb-pf-pnl" '
                 'data-sv-live-key="hb-pf-pnl">')


# ── 6. The dropdown is unchanged ─────────────────────────────────────────

class DropdownUnchangedTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_dd")
        _components()
        _tick(_config(self.user))
        _real(self.user, price="110", entry="100", stop="95")   # +10, +2R
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100",
               stop_loss=Decimal("90"))                          # +30, +1R
        self.client.force_login(self.user)
        self.body = _page(self.client)

    def test_open_pnl_and_open_r_in_the_dropdown_are_still_both_books(self):
        ctx = _ctx(self.user)
        self.assertEqual(dd_value(self.body, "OPEN P&L"),
                         ctx["panel_open_pnl_display"])
        self.assertEqual(dd_value(self.body, "OPEN P&L"), "+40.00")
        self.assertEqual(dd_value(self.body, "OPEN R"),
                         ctx["panel_open_r_display"])
        self.assertEqual(dd_value(self.body, "OPEN R"), "+3.00R")

    def test_value_still_agrees_with_the_cell(self):
        self.assertEqual(cell(self.body, "hb-pf-value"),
                         dd_value(self.body, "VALUE"))
        ctx = _ctx(self.user)
        self.assertEqual(cell(self.body, "hb-pf-value"),
                         f"{ctx['panel_currency_symbol']}"
                         f"{ctx['panel_portfolio_value']}")

    def test_the_sub_line_still_carries_only_positions_and_exposure(self):
        self.assertRegex(cell(self.body, "hb-pf-value"), r"^\D*[\d,]+$")
        m = re.search(r'data-sv-live="hb-pf-sub">(.*?)</span>\s*<div',
                      self.body, re.S)
        self.assertIsNotNone(m)
        self.assertRegex(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))),
                         r"^\s*2 pos · (\d+% in|— in)\s*$")

    def test_the_cell_reads_value_then_live_then_sub_then_dropdown(self):
        at = [self.body.index('data-sv-live="%s"' % name) for name in
              ("hb-pf-value", PNL_REGION, "hb-pf-sub", "hb-pf-detail")]
        self.assertEqual(at, sorted(at))
        # All four inside the one PORTFOLIO anchor.
        anchor = self.body.rindex('class="ip-cat ip-cat-link ip-cat-pf"', 0,
                                  at[0])
        self.assertNotIn('class="ip-cat ', self.body[anchor + 10:at[-1]])

    def test_no_venue_marker_leaks_into_a_dropdown_value(self):
        """tests/test_venue_split pins this for the pool cells; the new
        line is a cell line and not a .dv, and the dropdown is untouched."""
        self.assertIsNone(re.search(
            r'class="dv[^"]*"[^>]*>[^<]*<span class="sv-venue', self.body))


# ── 7. The line refreshes with the rest of the cell ──────────────────────

class RefreshTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_refresh")
        _components()
        _tick(_config(self.user))
        self.client.force_login(self.user)

    def test_the_line_is_a_live_region_the_source_carries(self):
        page = _page(self.client)
        self.assertIn(PNL_REGION, regions(page))
        self.assertIn('data-sv-live-key="%s"' % PNL_REGION, page)
        self.assertEqual(page.count("var LIVE_URL ="), 1)
        self.assertIn('var LIVE_URL = "%s"' % LIVE_SOURCE, page)

    def test_a_real_fill_changes_what_the_refresh_returns(self):
        before = _words(_page(self.client), PNL_REGION)
        self.assertTrue(before.startswith(f"LIVE {DASH}"), before)
        _real(self.user, price="110", entry="100")
        after = _words(_page(self.client), PNL_REGION)
        self.assertNotEqual(before, after)
        self.assertTrue(after.startswith("LIVE +10.00"), after)

    def test_a_venue_print_moving_changes_the_line(self):
        from bot_program import venue_mark
        trade = _real(self.user, price="110", entry="100")
        before = _words(_page(self.client), PNL_REGION)
        trade.refresh_from_db()
        self.assertTrue(venue_mark.stamp(trade, Decimal("115"),
                                         source="etoro", via="tick"))
        after = _words(_page(self.client), PNL_REGION)
        self.assertTrue(before.startswith("LIVE +10.00"), before)
        self.assertTrue(after.startswith("LIVE +15.00"), after)

    def test_a_fresh_print_clears_the_stale_word(self):
        from bot_program import venue_mark
        trade = _real(self.user, price="110", entry="100", hours_ago=3)
        self.assertIn("· stale", _words(_page(self.client), PNL_REGION))
        trade.refresh_from_db()
        self.assertTrue(venue_mark.stamp(trade, Decimal("112"),
                                         source="etoro", via="tick"))
        after = _words(_page(self.client), PNL_REGION)
        self.assertTrue(after.startswith("LIVE +12.00"), after)
        self.assertNotIn("stale", after)

    def test_the_other_regions_are_still_there(self):
        found = regions(_page(self.client))
        for name in ("hb-pf-value", "hb-pf-sub", "hb-pf-detail",
                     "hb-pos-count", "hb-pos-sub", "hb-pos-detail"):
            self.assertIn(name, found, name)


# ── 8. The sheet ─────────────────────────────────────────────────────────

class StyleTests(SimpleTestCase):
    def test_the_line_is_scoped_to_its_cell_and_kept_compact(self):
        """The rules located by selector, not by spelling: the cell's label
        and sub-line take 1.2 inside .ip-cat-pf only (the siblings keep the
        .ip-cat rules, which name no line-height); the line itself is 10px;
        the groups said apart are a step smaller; the markers sit under the
        venue convention, whose first rule test_venue_split slices from;
        the Portfolio page's wrapping sub-line beats the refinement layer
        by specificity; the phone tier never sees the line."""
        css = _sheet()
        self.assertRegex(_rule(css, ".ip-cat-pf .ip-label, .ip-cat-pf .ip-sub"),
                         r"line-height:\s*1\.2\b")
        self.assertNotIn("line-height", _rule(css, ".ip-cat .ip-label"))
        self.assertNotIn("line-height", _rule(css, ".ip-cat .ip-sub"))
        self.assertRegex(_rule(css, ".ip-cat .ip-pnl"), r"font-size:\s*10px")
        self.assertRegex(_rule(css, ".ip-cat .ip-pnl-apart"),
                         r"font-size:\s*9px")
        self.assertRegex(_rule(css, ".ip-cat .ip-pnl .ip-pnl-note"),
                         r"font-size:\s*8px")
        self.assertRegex(_rule(css, ".info-panel-scroll"),
                         r"height:\s*60px")
        convention = css.index("THE VENUE CONVENTION, NAMED ONCE")
        self.assertLess(convention, css.index(".sv-venue {"))
        self.assertLess(convention, css.index(".sv-venue--paper"))
        self.assertGreater(css.index(".ip-cat .ip-pnl .sv-venue"),
                           css.index(".sv-venue--demo"))
        self.assertNotIn("background", _rule(css, ".sv-venue--demo"))
        self.assertRegex(_rule(css, ".oc-strip-sub.oc-strip-sub--wrap"),
                         r"white-space:\s*normal")
        phone = _sheet("sv-responsive.css")
        self.assertNotIn("ip-pnl", phone)
        self.assertRegex(phone, r"\.info-panel-wrap, #ipRestorePill \{ "
                                r"display: none !important; \}")


# ── 9. The Portfolio page's head carries the same figure ─────────────────

class PortfolioPageTests(TestCase):
    def setUp(self):
        self.user = _user("hbl_pf")
        self.client.force_login(self.user)

    def _pf(self, url="/portfolio/"):
        return _page(self.client, url)

    def test_the_head_prints_the_live_figure_with_the_same_words(self):
        _real(self.user, price="110", entry="100", stop="95")   # +10, +2R
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")        # +30
        body = self._pf()
        got = pf_cells(body)
        self.assertEqual(got["pf.unrealized_live"], "+10.00")
        self.assertEqual(got["pf.unrealized"], "+40.00")
        self.assertEqual(got["pf.unrealized_live.sub"],
                         "+2.00R · paper +30.00")
        self.assertIn('<span class="sv-venue sv-venue--live">LIVE</span> '
                      'OPEN P&amp;L', body)
        self.assertIn("never added", _pf_live_title(body))

    def test_the_sub_line_wraps_and_keeps_every_figure(self):
        """An ellipsis cut "paper +30.00 apart · demo +4.00 apart" at every
        width; the sub-line wraps now, and says each figure in full."""
        _real(self.user, price="110", entry="100", stop="95")
        _real(self.user, symbol="ETHUSD", price="104", entry="100",
              env="demo")
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")
        body = self._pf()
        self.assertRegex(body, r'<span class="oc-strip-sub oc-strip-sub--wrap"'
                               r' data-sv-live-key="pf\.unrealized_live\.sub"')
        self.assertEqual(pf_cells(body)["pf.unrealized_live.sub"],
                         "+2.00R · paper +30.00 · demo +4.00")

    def test_no_real_row_is_a_dash(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")
        got = pf_cells(self._pf())
        self.assertEqual(got["pf.unrealized_live"], DASH)
        self.assertEqual(got["pf.unrealized"], "+30.00")
        self.assertIn("no real-money position open",
                      got["pf.unrealized_live.sub"].lower())

    def test_a_real_row_nothing_marked_is_a_dash_not_a_zero(self):
        _quote("XAUUSD", "2668", asset_class="commodity")
        _real(self.user, symbol="XAUUSD", entry="2650", stamp=False)
        got = pf_cells(self._pf())
        self.assertEqual(got["pf.unrealized_live"], DASH)
        self.assertIn("none marked", got["pf.unrealized_live.sub"])

    def test_a_demo_row_is_apart_and_not_live(self):
        _real(self.user, price="110", entry="100", env="demo")
        got = pf_cells(self._pf())
        self.assertEqual(got["pf.unrealized_live"], DASH)
        self.assertEqual(got["pf.unrealized_live.sub"],
                         "no real-money position open · demo +10.00")

    def test_a_partly_marked_real_book_says_so_on_the_page(self):
        _real(self.user, price="110", entry="100", stop="95")   # +10, +2R
        _quote("XAUUSD", "2668", asset_class="commodity")
        _real(self.user, symbol="XAUUSD", entry="2650", stamp=False)
        body = self._pf()
        got = pf_cells(body)
        self.assertEqual(got["pf.unrealized_live"], "+10.00")
        self.assertEqual(got["pf.unrealized_live.sub"],
                         "+2.00R · 1 of 2 marked")
        self.assertIn("Across 1 of 2 real-money positions: the other could "
                      "not be marked at the venue's rate", _pf_live_title(body))

    def test_a_stale_venue_print_is_said_on_the_page(self):
        _real(self.user, price="110", entry="100", stop="95", hours_ago=3)
        body = self._pf()
        got = pf_cells(body)
        self.assertEqual(got["pf.unrealized_live"], "+10.00")
        self.assertEqual(got["pf.unrealized_live.sub"],
                         "+2.00R · stale, 3 h old")
        self.assertIn("rests on the venue's last print, 3 h old",
                      _pf_live_title(body))

    def test_the_r_is_the_strips_r_summed_unrounded(self):
        """Three real rows at 1/3R each: the strip sums the unrounded R
        (+1.00R); the page summed the rows' two-decimal R (+0.99R)."""
        for sym in ("BTCUSD", "ETHUSD", "SOLUSD"):
            _real(self.user, symbol=sym, price="101", entry="100", stop="97")
        got = pf_cells(self._pf())
        self.assertTrue(got["pf.unrealized_live.sub"].startswith("+1.00R"),
                        got["pf.unrealized_live.sub"])
        _components()
        _tick(_config(self.user))
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_r_live_display"], "+1.00R")
        self.assertEqual(got["pf.unrealized_live.sub"],
                         ctx["panel_open_r_live_display"])
        self.assertEqual(got["pf.unrealized_live"],
                         ctx["panel_open_pnl_live_display"])

    def test_a_real_row_with_no_stop_reads_dash_r_with_its_reason(self):
        _real(self.user, price="110", entry="100")
        body = self._pf()
        self.assertEqual(pf_cells(body)["pf.unrealized_live.sub"], f"{DASH}R")
        self.assertIn("R needs an entry, the opening stop and a venue mark.",
                      _pf_live_title(body))

    def test_a_manual_position_is_counted_on_the_page(self):
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL", qty="2", entry="100")
        body = self._pf()
        got = pf_cells(body)
        self.assertEqual(got["pf.unrealized_live"], DASH)
        self.assertEqual(got["pf.unrealized_live.sub"],
                         "no real-money position open · 1 manual")
        self.assertIn("1 manual position states no venue",
                      _pf_live_title(body))

    def test_the_fragment_carries_the_same_cell(self):
        _real(self.user, price="110", entry="100", stop="95")
        page, frag = self._pf(), self._pf("/portfolio/live/")
        self.assertEqual(pf_cells(frag)["pf.unrealized_live"], "+10.00")
        self.assertEqual(pf_cells(frag)["pf.unrealized_live"],
                         pf_cells(page)["pf.unrealized_live"])
        self.assertEqual(pf_cells(frag)["pf.unrealized_live.sub"],
                         pf_cells(page)["pf.unrealized_live.sub"])

    def test_the_rows_carry_their_world_from_the_trade(self):
        from dashboard.views import _live_open_book
        from portfolio.services import get_or_create_default_portfolio
        _real(self.user, price="110", entry="100", env="demo")
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL")
        book = get_or_create_default_portfolio(user=self.user)
        _o, rows, _n, _u, _d = _live_open_book(self.user, book)
        worlds = {r["symbol"]: r["world"] for r in rows}
        self.assertEqual(worlds, {"BTCUSD": "demo", "AAPL": ""})
