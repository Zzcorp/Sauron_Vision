"""The book's notional is money, not quote-currency units (2026-10-04).

The weekly review of 2026-10-02 read a 10,000 book carrying "$10.84M of
forex exposure" (746x), a +194% day and a value of 42,834 — and the risk
gates, which scale every ceiling as a percentage of that value, loosened
to match. Every notional the book summed was price x quantity: right for a
dollar-quoted row, 150 times too big for a USDJPY row whose price is yen.
The P&L had been converted for a month (the sizing stamp value_per_unit);
the notional had not.

Pinned: the one multiplier (portfolio.services.usd_per_unit — the stamp
for a bot row, the live rate for a legacy forex row, 1 for everything
else, None when a forex rate cannot be read), every sum through it (the
Operations Center's deployed, the book value's marked and allocated, the
snapshot's exposure by class), the legacy forex P&L converted too, an
unreadable rate leaving the row unpriced rather than counted at 1, and
the Sharpe ratio the snapshot now writes from its own series.

Run with:  python manage.py test tests.test_quote_currency_notional
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from tests.test_portfolio_value_truth import (_book, _config, _position,
                                              _quote, _trade, _user, _value)

JPY_PER_USD = 150.0


class TheMultiplierTests(TestCase):

    def setUp(self):
        self.user = _user("qc_mult")
        self.pf = _book(self.user)

    def test_a_bot_row_carries_its_sizing_stamp(self):
        from portfolio.services import unified_open_positions, usd_per_unit
        _quote("USDJPY", "151", asset_class="forex")
        _trade(self.user, "USDJPY", qty="200", entry="150",
               config=_config(self.user, name="fx", asset_class="forex"),
               metadata={"value_per_unit": 1 / JPY_PER_USD})
        row = unified_open_positions(self.user, self.pf)[0]
        self.assertAlmostEqual(row.value_per_unit, 1 / JPY_PER_USD, places=9)
        self.assertAlmostEqual(usd_per_unit(row), 1 / JPY_PER_USD, places=9)

    def test_a_legacy_forex_row_converts_at_the_live_rate(self):
        from portfolio.services import usd_per_unit
        _quote("USDJPY", "151", asset_class="forex")
        row = _position(self.pf, "USDJPY", qty="200", entry="150",
                        current="150", asset_class="forex")
        self.assertAlmostEqual(usd_per_unit(row), 1 / 151.0, places=9)

    def test_a_dollar_quoted_pair_and_a_stock_are_one(self):
        from portfolio.services import usd_per_unit
        _quote("EURUSD", "1.1", asset_class="forex")
        eur = _position(self.pf, "EURUSD", qty="1000", entry="1.1",
                        current="1.1", asset_class="forex")
        aapl = _position(self.pf, "AAPL", qty="2", entry="100", current="100")
        self.assertEqual(usd_per_unit(eur), 1.0)
        self.assertEqual(usd_per_unit(aapl), 1.0)

    def test_an_unreadable_rate_is_none_never_a_silent_one(self):
        from portfolio.services import usd_per_unit
        _quote("GBPXYZ", "2.0", asset_class="forex")
        row = _position(self.pf, "GBPXYZ", qty="100", entry="2.0",
                        current="2.0", asset_class="forex")
        self.assertIsNone(usd_per_unit(row))


class EverySumIsInDollarsTests(TestCase):

    def setUp(self):
        self.user = _user("qc_sums")
        self.pf = _book(self.user)
        self.cash = float(self.pf.cash_available)

    def test_a_yen_quoted_bot_row_is_deployed_dollars(self):
        """200 USD of USDJPY at 151: notional about 201, never 30,200."""
        _quote("USDJPY", "151", asset_class="forex")
        _trade(self.user, "USDJPY", qty="200", entry="150",
               config=_config(self.user, name="fx", asset_class="forex"),
               metadata={"value_per_unit": 1 / JPY_PER_USD})
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.marked, 151 * 200 / JPY_PER_USD, places=2)
        self.assertAlmostEqual(book.unrealized, 200 / JPY_PER_USD, places=2)
        self.assertLess(book.marked, 300)
        # Paper: adds its P&L only — about 1.33 — and no yen anywhere.
        self.assertAlmostEqual(book.value, self.cash + 200 / JPY_PER_USD,
                               places=2)

    def test_a_yen_quoted_legacy_row_is_deployed_dollars_and_its_pnl_too(self):
        """The eToro sync's Position: 200 units of USDJPY, yen-quoted."""
        from dashboard.views_command import _open_book
        _quote("USDJPY", "151", asset_class="forex")
        _position(self.pf, "USDJPY", qty="200", entry="150", current="150",
                  asset_class="forex")
        rows, n_priced, unrealized, deployed = _open_book(self.user, self.pf)
        self.assertEqual(n_priced, 1)
        self.assertAlmostEqual(deployed, 200.0, places=2)      # 151 x 200 / 151
        self.assertAlmostEqual(unrealized, 200 / 151.0, places=2)
        self.assertAlmostEqual(rows[0].value_per_unit, 1 / 151.0, places=9)
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.marked, 200.0, places=2)
        # Funded (a legacy row): cash + its marked dollars, not its yen.
        self.assertAlmostEqual(book.value, self.cash + 200.0, places=2)
        self.assertAlmostEqual(book.funded_marked, 200.0, places=2)

    def test_the_snapshot_s_exposure_by_class_is_dollars(self):
        from portfolio.tasks import value_and_exposure
        _quote("USDJPY", "151", asset_class="forex")
        _trade(self.user, "USDJPY", qty="200", entry="150",
               config=_config(self.user, name="fx", asset_class="forex"),
               metadata={"value_per_unit": 1 / JPY_PER_USD})
        _quote("AAPL", "120", asset_class="stock")
        _position(self.pf, "AAPL", qty="2", entry="100")
        book, by_class, _s, _c = value_and_exposure(self.pf)
        self.assertAlmostEqual(by_class["forex"], 151 * 200 / JPY_PER_USD,
                               places=2)
        self.assertAlmostEqual(by_class["stock"], 240.0, places=2)
        self.assertAlmostEqual(sum(by_class.values()), book.marked, places=2)

    def test_an_unreadable_rate_leaves_the_row_unpriced(self):
        """A number the book cannot measure is left out and said, never
        counted at 1 — the module's rule, applied to the rate too."""
        _quote("GBPXYZ", "2.0", asset_class="forex")
        _position(self.pf, "GBPXYZ", qty="100", entry="2.0", current="2.0",
                  asset_class="forex")
        book = _value(self.user, self.pf)
        self.assertEqual((book.n_open, book.n_priced, book.n_unpriced),
                         (1, 0, 1))
        self.assertIsNone(book.value)
        self.assertIn("none with a live quote", book.coverage)

    def test_dollar_rows_are_exactly_as_before(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")
        _quote("AAPL", "120", asset_class="stock")
        _position(self.pf, "AAPL", qty="2", entry="100")
        book = _value(self.user, self.pf)
        self.assertAlmostEqual(book.marked, 570.0, places=2)
        self.assertAlmostEqual(book.value, self.cash + 240.0 + 30.0, places=2)


class TheSharpeTests(TestCase):

    def test_too_few_returns_or_no_variance_is_none(self):
        from portfolio.tasks import sharpe_of
        self.assertIsNone(sharpe_of([100, 101, 102]))
        self.assertIsNone(sharpe_of([100] * 20))
        self.assertIsNone(sharpe_of([]))

    def test_a_rising_series_has_a_positive_annualised_sharpe(self):
        from portfolio.tasks import sharpe_of
        values = [100 + i + (0.5 if i % 2 else 0) for i in range(15)]
        s = sharpe_of(values)
        self.assertIsNotNone(s)
        self.assertGreater(s, 0)
        self.assertLess(sharpe_of([100 - i for i in range(15)]) or 0, 0)

    def test_the_snapshot_writes_it_from_its_own_series(self):
        from portfolio.models import PortfolioSnapshot
        from portfolio.tasks import _snapshot_book
        user = _user("qc_sharpe")
        pf = _book(user)
        today = date(2026, 10, 4)
        for i in range(12):
            PortfolioSnapshot.objects.create(
                portfolio=pf, date=today - timedelta(days=12 - i),
                total_value=Decimal(str(10000 + 7 * i + (3 if i % 3 else 0))),
                cash=pf.cash_available, daily_pnl=Decimal("0"),
                daily_pnl_pct=0.0, cumulative_pnl_pct=0.0, max_drawdown=0.0)
        out = _snapshot_book(pf, today, today - timedelta(days=1))
        self.assertEqual(out["status"], "ok")
        snap = PortfolioSnapshot.objects.get(portfolio=pf, date=today)
        self.assertIsNotNone(snap.sharpe_ratio)


class TheConstantsTests(SimpleTestCase):

    def test_the_sharpe_needs_ten_returns_and_a_trading_year(self):
        from portfolio.tasks import SHARPE_MIN_RETURNS, TRADING_DAYS
        self.assertEqual((SHARPE_MIN_RETURNS, TRADING_DAYS), (10, 252))
