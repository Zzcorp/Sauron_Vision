"""The eToro sync, which runs against the shared real-money "Main" book.

Two ways it recorded a book that was not the one held.

A position with no ticker. eToro's API is instrumentId-based and can answer
without a symbol; `pos.get("symbol", "")` was passed unguarded to
`Instrument.objects.get_or_create(symbol=symbol)`, and Instrument.symbol is
unique but "" is a legal value. So every unsymboled position — this sync and
every future one — resolved to the SAME blank row, and the Position upsert
beneath it overwrote that one row on each iteration. N distinct real-money
holdings were recorded as one, carrying the last one's quantity, entry and
P&L, and the book value and the risk denominator were wrong by whatever the
discarded positions were worth.

A price of zero. The mark guard was `current_rate not in (None, "")`, and 0
satisfies it, so a halted instrument's currentRate of 0 was written into
LiveQuote as a real mark under a source name the priority table does not
carry — where it held that zero against yfinance and coingecko for the full
300-second hold while the position valued at nothing.

Run with:  python manage.py test tests.test_etoro_sync
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

BALANCE = {"equity": 50000, "availableBalance": 10000}


def _position(symbol=None, *, rate=160, amount=10, entry=150, pid=None):
    pos = {
        "amount": amount, "openRate": entry, "currentRate": rate,
        "isBuy": True, "netProfit": 100, "netProfitPercentage": 6.6,
    }
    if symbol is not None:
        pos["symbol"] = symbol
        pos["name"] = symbol
    if pid is not None:
        pos["positionId"] = pid
    return pos


def _sync(positions):
    from market_data.adapters import etoro_adapter
    with patch.object(etoro_adapter.EtoroClient, "is_configured",
                      return_value=True), \
         patch.object(etoro_adapter.EtoroClient, "get_positions",
                      return_value={"positions": positions}), \
         patch.object(etoro_adapter.EtoroClient, "get_account_balance",
                      return_value=BALANCE):
        return etoro_adapter.sync_etoro_positions()


class UnsymboledPositionTests(TestCase):
    def test_two_nameless_holdings_do_not_become_one_blank_instrument(self):
        from instruments.models import Instrument

        _sync([_position(pid=1, amount=5), _position(pid=2, amount=7)])

        self.assertFalse(Instrument.objects.filter(symbol="").exists())
        self.assertEqual(Instrument.objects.count(), 0)

    def test_a_nameless_holding_is_counted_out_loud_not_swallowed(self):
        out = _sync([_position("AAPL"), _position(pid=2), _position(pid=3)])

        self.assertEqual(out["synced"], 1)
        self.assertEqual(out["skipped_unsymboled"], 2)

    def test_a_named_holding_beside_nameless_ones_is_recorded_intact(self):
        from portfolio.models import Position

        _sync([_position(pid=1, amount=5), _position("AAPL", amount=10),
               _position(pid=2, amount=7)])

        rows = list(Position.objects.all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].instrument.symbol, "AAPL")
        self.assertEqual(rows[0].quantity, Decimal("10.00000000"))

    def test_a_blank_string_symbol_counts_as_no_symbol(self):
        from instruments.models import Instrument

        out = _sync([_position("", pid=1), _position("   ", pid=2)])

        self.assertEqual(out["skipped_unsymboled"], 2)
        self.assertEqual(Instrument.objects.count(), 0)

    def test_a_lowercase_ticker_resolves_to_the_catalogue_row(self):
        """Two Instrument rows for one holding would split the book in half
        and quote only one of them."""
        from instruments.models import Instrument

        Instrument.objects.create(symbol="AAPL", name="Apple",
                                  asset_class="stock")
        _sync([_position("aapl")])

        self.assertEqual(Instrument.objects.filter(symbol__iexact="AAPL").count(), 1)


class BrokerMarkTests(TestCase):
    def test_a_real_mark_reaches_the_one_mark_table(self):
        from market_data.models import LiveQuote

        _sync([_position("AAPL", rate=160)])

        quote = LiveQuote.objects.get(instrument__symbol="AAPL")
        self.assertEqual(quote.last, Decimal("160.00000000"))
        self.assertEqual(quote.source, "etoro")

    def test_a_halted_instruments_zero_is_refused_as_a_price(self):
        from market_data.models import LiveQuote

        _sync([_position("HALT", rate=0)])

        self.assertFalse(LiveQuote.objects.filter(
            instrument__symbol="HALT").exists())

    def test_a_zero_mark_does_not_displace_a_real_one(self):
        """The zero used to be written under a source ranked at the
        anonymous default, which then held it against every poller for the
        full precedence window."""
        from instruments.models import Instrument
        from market_data.models import LiveQuote

        inst = Instrument.objects.create(symbol="HALT", name="HALT",
                                         asset_class="stock")
        LiveQuote.objects.create(instrument=inst, last=Decimal("42"),
                                 change_pct=Decimal("0"), source="yfinance")

        _sync([_position("HALT", rate=0)])

        self.assertEqual(LiveQuote.objects.get(instrument=inst).last,
                         Decimal("42.00000000"))

    def test_an_unusable_rate_leaves_the_position_recorded_but_unpriced(self):
        from market_data.models import LiveQuote
        from portfolio.models import Position

        out = _sync([_position("ODD", rate="n/a")])

        self.assertEqual(out["synced"], 1)
        self.assertEqual(Position.objects.count(), 1)
        self.assertFalse(LiveQuote.objects.exists())
