"""A price shown at the precision its own venue quotes it in.

Every surface hardcoded its own answer — `floatformat:4` in the headband
and the watchlist rail, `toFixed(4)` in the live painter, `toFixed(2)`
in the ticker — so AAPL rendered as `227.5300`, a JPY cross carried one
digit more than the broker's own ticket, and a value CHANGED SHAPE the
moment it ticked, because the server had written four decimals and the
painter repainted two.

The rule follows the venue, not a rounding preference: forex is quoted
in pips (three decimals on a JPY cross, five elsewhere), and everything
else scales with magnitude, because the question is how many digits are
meaningful rather than what the asset class is called.

Run with:  python manage.py test tests.test_price_precision
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


class TheVenueDecidesTests(SimpleTestCase):
    def _f(self, v, ac="", sym=""):
        from core.price_format import format_price
        return format_price(v, ac, sym)

    def test_a_share_gets_two(self):
        self.assertEqual(self._f(227.53, "stock", "AAPL"), "227.53")

    def test_a_share_does_not_get_four(self):
        """The complaint: 227.5300 reads as a machine that does not know
        what it is showing."""
        self.assertNotIn("227.5300", self._f(227.53, "stock", "AAPL"))

    def test_a_forex_major_keeps_its_pip(self):
        self.assertEqual(self._f(1.08425, "forex", "EURUSD"), "1.08425")

    def test_a_jpy_cross_gets_three_not_five(self):
        """What the broker's ticket shows. Five would be a digit the
        venue does not quote."""
        self.assertEqual(self._f(148.325, "forex", "USDJPY"), "148.325")

    def test_a_jpy_cross_is_detected_by_its_quote_side(self):
        from core.price_format import price_decimals
        self.assertEqual(price_decimals(1, "forex", "GBPJPY"), 3)
        self.assertEqual(price_decimals(1, "forex", "EURGBP"), 5)

    def test_bitcoin_gets_two(self):
        self.assertEqual(self._f(67432.5, "crypto", "BTCUSD"), "67432.50")

    def test_a_sub_dollar_token_gets_four(self):
        self.assertEqual(self._f(Decimal("0.8542"), "crypto", "ADAUSD"),
                         "0.8542")

    def test_a_tiny_token_does_not_round_to_zero(self):
        """Two decimals would render this as 0.00."""
        self.assertEqual(self._f(Decimal("0.00002341"), "crypto", "SHIBUSD"),
                         "0.00002341")

    def test_a_missing_price_is_a_dash_not_a_zero(self):
        self.assertEqual(self._f(None, "stock", "AAPL"), "—")
        self.assertEqual(self._f("", "stock", "AAPL"), "—")

    def test_a_junk_value_never_raises(self):
        self.assertEqual(self._f("not a price", "stock", "AAPL"), "—")

    def test_no_thousands_separator(self):
        """These sit in monospaced columns; a comma that appears at
        1,000 and vanishes at 999 makes the column jump."""
        self.assertEqual(self._f(1234.5, "stock", "AAPL"), "1234.50")


class ThePainterAgreesWithTheServerTests(TestCase):
    """The count is rendered onto the element because the painter has
    only a symbol and a number — it cannot tell forex from a share."""

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.user = User.objects.create_user("px_u", password="x")
        self.client.force_login(self.user)
        inst = Instrument.objects.create(symbol="EURUSD", name="Euro",
                                         asset_class="forex", is_active=True)
        LiveQuote.objects.create(instrument=inst, last=Decimal("1.08425"),
                                 bid=Decimal("1.08420"),
                                 ask=Decimal("1.08430"), source="oanda")

    def test_the_element_carries_the_decision(self):
        body = self.client.get("/instruments/EURUSD/").content.decode()
        self.assertIn('data-decimals="5"', body)

    def test_the_painter_reads_it_rather_than_guessing(self):
        from pathlib import Path

        from django.conf import settings
        shell = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        seg = shell.split("function applyTick")[1][:2800]
        # The painting STATEMENTS, not the prose around them — the
        # comment beside them quotes the old shape on purpose.
        self.assertIn("last.toFixed(svDecimals(", seg)
        self.assertNotIn("textContent = last.toFixed(4)", seg)
        self.assertNotIn("textContent = last.toFixed(2)", seg)


class BidAskSitsBesideTheButtonsThatUseItTests(TestCase):
    """LONG lifts the ask and SHORT hits the bid, so the spread is the
    first cost of the decision those buttons take. It was only in a
    stats list further down the page."""

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.user = User.objects.create_user("ba_u", password="x")
        self.client.force_login(self.user)
        self.inst = Instrument.objects.create(
            symbol="BRNUSD", name="Brent", asset_class="commodity",
            is_active=True)
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("82.45"),
                                 bid=Decimal("82.43"), ask=Decimal("82.47"),
                                 source="ibkr")

    def test_bid_and_ask_are_on_the_page_head(self):
        body = self.client.get("/instruments/BRNUSD/").content.decode()
        head = body.split("dtl-actions")[1][:1200]
        self.assertIn('data-dq="bid"', head)
        self.assertIn('data-dq="ask"', head)

    def test_the_spread_is_shown_and_correct(self):
        body = self.client.get("/instruments/BRNUSD/").content.decode()
        self.assertIn('data-dq="spread"', body)
        self.assertIn("0.04", body)

    def test_a_quote_with_no_book_shows_no_row(self):
        from market_data.models import LiveQuote
        LiveQuote.objects.filter(instrument=self.inst).update(bid=None, ask=None)
        body = self.client.get("/instruments/BRNUSD/").content.decode()
        self.assertNotIn('data-dq="bid"', body)

    def test_the_spread_property_is_none_without_both_sides(self):
        from market_data.models import LiveQuote
        q = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(q.spread, Decimal("0.04"))
        q.bid = None
        self.assertIsNone(q.spread)


class NoSurfaceStillHardcodesFourTests(SimpleTestCase):
    """A tripwire on the shape, so this cannot come back one template at
    a time."""

    def test_the_headband_and_rail_use_the_shared_tag(self):
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        dh = (base / "templates" / "_partials" / "dh_item.html").read_text(
            encoding="utf-8")
        self.assertNotIn("floatformat:4", dh)
        self.assertIn("{% px ", dh)

        shell = (base / "templates" / "base.html").read_text(encoding="utf-8")
        rail = shell.split('class="wl-item')[1][:600]
        self.assertNotIn("floatformat:4", rail)
