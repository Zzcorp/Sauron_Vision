"""The price belongs on the button that trades at it.

The instrument header used to carry five separate things: LONG and SHORT
buttons with no prices, and BID / ASK / SPREAD as three loose cells in a
strip beside them. The template's own comment explained that LONG lifts
the ask and SHORT hits the bid — which is work the markup should have
been doing, and which the operator was instead doing by eye at the moment
of committing money.

The ticket is one control: two sides that trade and one middle that
prices them. It renders in the header and again as an overlay on the
EXPANDED chart, where the card covers the header and there would
otherwise be nothing on screen to trade with.

THE PART THAT MATTERS MOST: those `data-dq` hooks existed from the day
bid/ask shipped and NOTHING ever wrote to them. The numbers were
server-rendered at first paint and frozen for the life of the tab. That
was survivable in a stats row. It is not survivable on a BUY button, so
this file pins the repaint, the two-ticket case, the staleness bound, and
the refusal to print a zero for a price nobody quoted.

Run with:  python manage.py test tests.test_deal_ticket
"""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase


def ticket(**ctx):
    base = {"symbol": "EURUSD", "quote": None,
            "asset_class": "forex", "decimals": 5}
    base.update(ctx)
    return render_to_string("_partials/deal_ticket.html", base)


def widget(**ctx):
    base = {"chart_id": "t", "symbol": "EURUSD",
            "height": "420", "timeframe": "1d"}
    base.update(ctx)
    return render_to_string("_partials/chart_widget.html", base)


def live_js():
    return (Path(settings.BASE_DIR) / "static" / "js"
            / "sv-instrument-live.js").read_text(encoding="utf-8")


def css():
    return (Path(settings.BASE_DIR) / "static" / "css"
            / "sauron.css").read_text(encoding="utf-8")


class _Q:
    """A LiveQuote stand-in — the partial only reads three fields."""

    def __init__(self, bid=None, ask=None, spread=None):
        self.bid, self.ask, self.spread = bid, ask, spread


class TheSideCarriesItsOwnPriceTests(TestCase):

    def test_short_trades_the_bid_and_long_trades_the_ask(self):
        """The whole point. Getting these the wrong way round would put
        the operator on the wrong side of the spread every time."""
        html = ticket(quote=_Q(bid="1.10415", ask="1.10425",
                               spread="0.00010"))
        short = html.split("tk-short", 1)[1].split("</button>", 1)[0]
        long_ = html.split("tk-long", 1)[1].split("</button>", 1)[0]
        self.assertIn('data-dq="bid"', short)
        self.assertIn('data-dq="ask"', long_)

    def test_each_side_calls_the_one_manual_trade_engine(self):
        """Two calls, one per side — the same engine the popups and the
        watchlist rail use. Counting the guarded form, not the bare name:
        `window.x && window.x(...)` names it twice per button."""
        html = ticket()
        self.assertEqual(html.count("svTakeTradeAsset('EURUSD'"), 2)
        self.assertIn("'SELL'", html)
        self.assertIn("'BUY'", html)

    def test_the_middle_is_not_a_button(self):
        """Nothing trades at the spread."""
        mid = ticket().split("tk-mid", 1)[1].split("</span>", 1)[0]
        self.assertNotIn("<button", mid)

    def test_a_missing_side_is_an_em_dash_and_never_a_zero(self):
        """The house rule, and it matters most where the number sits on
        a button that opens a position."""
        html = ticket(quote=None)
        self.assertIn("sv-unknown", html)
        self.assertNotIn(">0<", html)
        self.assertNotIn("0.00", html)

    def test_both_sides_are_named_for_assistive_tech(self):
        html = ticket()
        self.assertIn("aria-label=\"Short EURUSD at the bid\"", html)
        self.assertIn("aria-label=\"Long EURUSD at the ask\"", html)


class TheExpandedChartCarriesOneTooTests(TestCase):

    def test_it_is_opt_in(self):
        """The widget documents itself as reusable; a page that has no
        live quote poller must not get trade buttons that cannot update."""
        self.assertNotIn('class="sv-chart-ticket"', widget())

    def test_and_the_instrument_page_opts_in(self):
        html = widget(ticket=True, asset_class="forex", decimals=5)
        self.assertIn('class="sv-chart-ticket"', html)
        self.assertIn("svTakeTradeAsset", html)

    def test_ask_sauron_rides_along_in_small(self):
        html = widget(ticket=True, asset_class="forex", decimals=5)
        self.assertIn("sv-chart-ask", html)
        self.assertIn('data-ask-sauron="EURUSD"', html)

    def test_it_shows_only_in_the_expanded_states(self):
        """At normal size the header's own ticket is inches away; a
        second one there is clutter."""
        html = widget(ticket=True, asset_class="forex", decimals=5)
        self.assertIn(".sv-chart-ticket {\n    display: none;", html)
        self.assertIn(".sv-candle-container.sv-chart-tall .sv-chart-ticket",
                      html)
        self.assertIn(".sv-candle-container.sv-chart-fs .sv-chart-ticket",
                      html)

    def test_it_is_not_in_the_toolbar(self):
        """That toolbar already carries forty controls and wraps to two
        rows, which is what was clipping the time axis. Buying the ticket
        by making the chart worse is not a trade worth taking.

        Asserted by position: the ticket sits AFTER the toolbar's last
        control group and BEFORE the canvas — a sibling of the toolbar,
        not another thing inside it to wrap.
        """
        html = widget(ticket=True, asset_class="forex", decimals=5)
        last_group = html.index("sv-chart-drawing-btns")
        tk = html.index('class="sv-chart-ticket"')
        canvas = html.index('class="sv-chart-body"')
        self.assertLess(last_group, tk, "ticket precedes the toolbar's end")
        self.assertLess(tk, canvas, "ticket is not after the canvas")
        # And no toolbar control follows it — it did not land mid-toolbar.
        self.assertNotIn("sv-ctl-btn", html[tk:canvas])
        self.assertNotIn("sv-tf-btn", html[tk:canvas])

    def test_it_rides_inside_the_container_so_the_portal_takes_it(self):
        html = widget(ticket=True, asset_class="forex", decimals=5)
        body = html.split('class="sv-candle-container', 1)[1]
        self.assertIn("sv-chart-ticket", body)


class ThePricesOnTheButtonsAreLiveTests(TestCase):
    """They were not. For the whole life of the feature."""

    def test_the_endpoint_serves_the_three_numbers(self):
        from pathlib import Path as P
        src = (P(settings.BASE_DIR) / "dashboard" / "views.py").read_text(
            encoding="utf-8")
        seg = src.split("def instrument_preview_api", 1)[1][:2600]
        for key in ('"bid"', '"ask"', '"spread"', '"quote_age_seconds"'):
            self.assertIn(key, seg, key)

    def test_the_client_repaints_them(self):
        self.assertIn("function paintDq", live_js())

    def test_it_repaints_every_ticket_on_the_page_not_the_first(self):
        """The page carries two — the header's and the expanded chart's.
        A repaint that found only one would leave the other lying."""
        js = live_js()
        self.assertIn("querySelectorAll('[data-dq=\"' + k + '\"]')", js)

    def test_a_missing_price_blanks_rather_than_zeroes(self):
        self.assertIn('sv-unknown', live_js())

    def test_a_fossil_quote_stops_claiming_a_price(self):
        """A stale number on a BUY button is worse than no number."""
        js = live_js()
        self.assertIn("STALE_S", js)
        self.assertIn("tk-stale", js)

    def test_bid_and_ask_paint_even_when_last_is_missing(self):
        """A row can carry both sides and no `last`, and the ticket trades
        off the two sides — so the price guard must not suppress them."""
        js = live_js()
        i = js.find("paintDq(d);")
        j = js.find("if (d.price == null) return;")
        self.assertGreater(i, 0)
        self.assertGreater(j, i, "paintDq must run before the price guard")

    def test_the_stale_class_is_styled(self):
        self.assertIn(".sv-ticket.tk-stale", css())


class TheHeaderKeepsOnlyOneOfEachTests(TestCase):

    def _page(self):
        return (Path(settings.BASE_DIR) / "templates" / "dashboard"
                / "instrument_detail.html").read_text(encoding="utf-8")

    def test_the_loose_price_strip_is_gone(self):
        """Its cells are on the buttons now; leaving the strip would show
        every number twice."""
        page = self._page()
        self.assertNotIn('class="dtl-quote', page)
        self.assertNotIn('class="dq-cell"', page)

    def test_and_so_are_the_styles_that_dressed_it(self):
        """Dead CSS outlives the markup it was written for and reads as
        live to the next person."""
        page = self._page()
        for dead in (".dq-cell {", ".dq-bid {", ".dq-ask {",
                     ".dtl-quote {"):
            self.assertNotIn(dead, page, dead)

    def test_the_header_uses_the_shared_partial(self):
        page = self._page()
        self.assertIn("_partials/deal_ticket.html", page)

    def test_the_auxiliary_controls_are_one_group(self):
        page = self._page()
        self.assertIn('class="dtl-aux"', page)
        aux = page.split('class="dtl-aux"', 1)[1].split("</span>", 1)[0]
        self.assertIn("data-ask-sauron", aux)

    def test_the_chart_include_passes_the_ticket_through(self):
        page = self._page()
        inc = [ln for ln in page.splitlines() if "chart_widget.html" in ln][0]
        self.assertIn("ticket=True", inc)
        self.assertIn("quote=quote", inc)
