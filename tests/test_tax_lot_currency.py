"""The currency a tax lot's realised gain is booked in.

`TaxLotConsumption.realized_gain` is read by every tax report as account
currency, and this was the one money path on the platform that never
converted. `(sale - cost) x qty` on a USDJPY row is a YEN figure: a trade
whose `pnl` column correctly said 33.20 dollars was filed in the tax ledger
as a gain of 5,000 — right sign, right symbol, 150x wrong, and nothing about
the row looked odd. Every other close path multiplies by the entry-time rate
frozen in `metadata["value_per_unit"]`; this one now does too, so a
consumption and the `pnl` on the trade that caused it can be added together.

Run with:  python manage.py test tests.test_tax_lot_currency
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="txc_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, asset_class, name):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="paper",
        symbols=[], capital=Decimal("100000"), base_currency="USD",
    )


def _closed_trade(cfg, *, symbol, qty, entry, exit_price, metadata=None,
                  asset_class=None):
    """A BUY that has opened and closed, with the lot already booked."""
    from bot_program.models import AssetBotTrade
    from bot_program.tax_lots import open_lot
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class, symbol=symbol,
        side="BUY", qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        status="OPEN", paper=True, metadata=metadata or {},
    )
    open_lot(t)
    t.exit_price = Decimal(str(exit_price))
    t.status = "CLOSED"
    t.closed_at = timezone.now()
    t.save()
    return t


class ForexLotCurrencyTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user, "forex", "FX")

    def _usdjpy(self):
        # 10,000 USDJPY bought at 150.00, out at 150.50. The entry-time rate
        # of one yen in dollars is what sizing froze on the row.
        return _closed_trade(
            self.cfg, symbol="USDJPY", qty=10000, entry="150.00",
            exit_price="150.50", metadata={"value_per_unit": 0.00664})

    def test_a_yen_gain_is_filed_in_dollars_not_in_yen(self):
        from bot_program.tax_lots import close_lots_for
        cons = close_lots_for(self._usdjpy())

        self.assertEqual(len(cons), 1)
        # 0.50 x 10,000 x 0.00664 = 33.20 USD, not 5,000 of quote currency.
        self.assertEqual(cons[0].realized_gain, Decimal("33.2000"))

    def test_the_tax_ledger_agrees_with_the_pnl_on_the_same_trade(self):
        """A consumption and the trade row that caused it have to be
        addable — one saying 33 dollars while the other says 5,000 is a
        ledger nobody can reconcile."""
        from bot_program.asset_engine.forex_bot import ForexBot
        from bot_program.tax_lots import close_lots_for

        trade = self._usdjpy()
        cons = close_lots_for(trade)
        booked = ForexBot(self.cfg)._trade_pnl(trade, trade.exit_price)

        self.assertAlmostEqual(float(cons[0].realized_gain), float(booked),
                               places=4)

    def test_a_legacy_row_with_no_frozen_rate_still_books_something(self):
        """No `value_per_unit` (a pre-sizing row) falls back to 1 — the old
        quote-currency behaviour — rather than raising into the close path."""
        from bot_program.tax_lots import close_lots_for
        trade = _closed_trade(self.cfg, symbol="EURUSD", qty=1000,
                              entry="1.1000", exit_price="1.1050")
        cons = close_lots_for(trade)
        self.assertEqual(len(cons), 1)
        self.assertEqual(cons[0].realized_gain, Decimal("5.0000"))


class OtherClassesUnchangedTests(TestCase):
    def setUp(self):
        self.user = _user("txc_other")

    def test_a_stock_lot_books_the_plain_price_difference(self):
        from bot_program.tax_lots import close_lots_for
        cfg = _cfg(self.user, "stock", "ST")
        trade = _closed_trade(cfg, symbol="AAPL", qty=10, entry="100",
                              exit_price="110")
        cons = close_lots_for(trade)
        self.assertEqual(cons[0].realized_gain, Decimal("100.0000"))

    def test_an_options_lot_still_carries_the_contract_multiplier(self):
        from bot_program.tax_lots import close_lots_for
        cfg = _cfg(self.user, "options", "OPT")
        trade = _closed_trade(cfg, symbol="AAPL", qty=2, entry="5",
                              exit_price="7", metadata={"multiplier": 100})
        cons = close_lots_for(trade)
        self.assertEqual(cons[0].realized_gain, Decimal("400.0000"))
