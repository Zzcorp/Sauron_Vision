"""The concentration panel has to be able to see the book.

`analyze_exposure` filtered `Position` on `is_open`, read `market_value` and
read `side` — three names that do not exist on the model, which tracks open
via `closed_at` and side via `direction`. `QuerySet.filter()` resolves field
names eagerly, so the FieldError landed in the function's bare except and it
returned `{}` on every call it has ever had. On the page that is an empty
chart with no error message: a book 80% in one sector and "you have no
concentration" render identically, and the operator arms a bot on the
strength of a blank panel.

Run with:  python manage.py test tests.test_exposure_panel
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _portfolio(name="expo_book"):
    from portfolio.models import Portfolio
    return Portfolio.objects.create(
        name=name, initial_capital=Decimal("100000"),
        current_value=Decimal("100000"), cash_available=Decimal("100000"),
        currency="USD",
    )


def _instrument(symbol, asset_class="stock", sector="Technology",
                currency="USD"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "sector": sector, "currency": currency})
    return inst


def _position(pf, inst, *, qty, entry, current=None, direction="long",
              closed=False):
    from portfolio.models import Position
    return Position.objects.create(
        portfolio=pf, instrument=inst, direction=direction,
        quantity=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        current_price=Decimal(str(current if current is not None else entry)),
        opened_at=timezone.now(),
        closed_at=timezone.now() if closed else None,
    )


class ExposureBreakdownTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="expo_u", password="x")
        self.pf = _portfolio()

    def test_open_positions_reach_the_breakdown_at_all(self):
        from strategies.portfolio_analyzer import analyze_exposure
        _position(self.pf, _instrument("AAPL"), qty=100, entry=150)

        out = analyze_exposure(self.pf)

        self.assertEqual(out.get("total"), 15000.0)
        self.assertEqual(out["by_asset_class"], {"stock": 1.0})
        self.assertEqual(out["by_sector"], {"Technology": 1.0})
        self.assertEqual(out["by_currency"], {"USD": 1.0})

    def test_a_concentrated_book_reports_its_concentration(self):
        """The number the operator opens this panel to see."""
        from strategies.portfolio_analyzer import analyze_exposure
        _position(self.pf, _instrument("AAPL"), qty=100, entry=800)
        _position(self.pf, _instrument("XOM", sector="Energy"),
                  qty=100, entry=200)

        out = analyze_exposure(self.pf)

        self.assertEqual(out["by_sector"]["Technology"], 0.8)
        self.assertEqual(out["by_sector"]["Energy"], 0.2)

    def test_a_closed_position_is_not_exposure(self):
        from strategies.portfolio_analyzer import analyze_exposure
        _position(self.pf, _instrument("AAPL"), qty=100, entry=150)
        _position(self.pf, _instrument("MSFT"), qty=100, entry=400,
                  closed=True)

        out = analyze_exposure(self.pf)

        self.assertEqual(out["total"], 15000.0)

    def test_a_short_is_gross_exposure_and_negative_net(self):
        from strategies.portfolio_analyzer import analyze_exposure
        _position(self.pf, _instrument("AAPL"), qty=100, entry=150)
        _position(self.pf, _instrument("TSLA", sector="Autos"), qty=100,
                  entry=250, direction="short")

        out = analyze_exposure(self.pf)

        self.assertEqual(out["gross"], 40000.0)
        self.assertEqual(out["net"], -10000.0)
        self.assertEqual(out["long_value"], 15000.0)
        self.assertEqual(out["short_value"], 25000.0)

    def test_a_repriced_position_is_valued_at_the_current_price(self):
        from strategies.portfolio_analyzer import analyze_exposure
        _position(self.pf, _instrument("AAPL"), qty=100, entry=150,
                  current=170)

        self.assertEqual(analyze_exposure(self.pf)["total"], 17000.0)

    def test_an_empty_book_says_empty_rather_than_nothing(self):
        from strategies.portfolio_analyzer import analyze_exposure
        out = analyze_exposure(self.pf)
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["by_asset_class"], {})


class CorrelationMatrixTests(TestCase):
    def test_the_matrix_gets_as_far_as_asking_for_bars(self):
        """Same dead field name in the sibling function: it returned an empty
        matrix before it ever looked at a position."""
        from unittest.mock import MagicMock, patch
        from strategies.portfolio_analyzer import calculate_correlation_matrix
        pf = _portfolio("corr_book")
        _position(pf, _instrument("AAPL"), qty=10, entry=150)

        loader = MagicMock(return_value=None)
        with patch("signals.smc.dataframe.load_ohlcv", loader):
            calculate_correlation_matrix(pf)

        self.assertEqual(loader.call_args[0][0], "AAPL")
