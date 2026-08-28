"""The exit price stops being a guess where the broker knows the answer.

Stock and forex stops rest AT the broker, so for most of those trades the
exit is a leg this platform never submitted and never saw print.
Reconciliation therefore booked a ticker read taken minutes later, flagged
`exit_price_inferred` — honest, and it means a large share of the track
record is estimates wearing exactly the shape of measurements.

That matters because `realized_r` is computed from whatever lands there,
and the promotion gate and the meta-allocator both read `realized_r`. An
estimate is a fine number to show an operator and a poor one to promote a
rule on.

The identifier this needs was already on the row — the protective handles
recorded at entry (`protective_stop_id`, `protective_trade_id`). Nothing
new had to be stored; the platform simply never asked.

Run with:  python manage.py test tests.test_real_fills
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


class _Trade:
    """Enough of an AssetBotTrade for a client to read its handles."""

    def __init__(self, **meta):
        self.metadata = meta
        self.symbol = "AAPL"


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


# ═══ Alpaca — the stop leg is an order, and a filled order names its price

class AlpacaReadsItsOwnStopFillTests(SimpleTestCase):

    def _t(self, payload, **meta):
        from bot_program.engine.alpaca_client import AlpacaTrader
        c = AlpacaTrader("k", "s")
        sess = MagicMock()
        sess.get.return_value = _resp(payload)
        c._session = sess
        return c, _Trade(**meta)

    def test_a_filled_stop_leg_gives_the_real_price(self):
        c, t = self._t({"status": "filled", "filled_avg_price": "189.42",
                        "filled_qty": "10"},
                       protective_stop_id="sl1")
        got = c.closing_fill(t)
        self.assertEqual(got["price"], 189.42)
        self.assertEqual(got["qty"], 10.0)
        self.assertIn("sl1", got["source"])

    def test_a_cancelled_leg_is_not_a_fill(self):
        """A cancelled stop carries the price it was RESTING at — which is
        precisely the level the position did NOT exit at. Booking it would
        be worse than the ticker estimate it replaced."""
        c, t = self._t({"status": "canceled", "filled_avg_price": "190.00"},
                       protective_stop_id="sl1")
        self.assertIsNone(c.closing_fill(t))

    def test_a_leg_still_resting_is_not_a_fill(self):
        c, t = self._t({"status": "accepted", "filled_avg_price": None},
                       protective_stop_id="sl1")
        self.assertIsNone(c.closing_fill(t))

    def test_the_named_stop_is_preferred_over_the_flat_list(self):
        """`protective_order_ids` does not say which id is which, and on a
        long bracket Alpaca returns the take-profit first."""
        c, t = self._t({"status": "filled", "filled_avg_price": "189.42"},
                       protective_stop_id="sl1",
                       protective_order_ids=["tp1", "sl1"])
        c.closing_fill(t)
        self.assertIn("/v2/orders/sl1", c._session.get.call_args[0][0])

    def test_no_handles_means_no_answer(self):
        c, t = self._t({}, )
        self.assertIsNone(c.closing_fill(t))

    def test_an_unreachable_broker_answers_none_not_a_number(self):
        from bot_program.engine.alpaca_client import AlpacaTrader
        c = AlpacaTrader("k", "s")
        sess = MagicMock()
        sess.get.side_effect = RuntimeError("no route")
        c._session = sess
        self.assertIsNone(c.closing_fill(_Trade(protective_stop_id="sl1")))


# ═══ OANDA — protection rides the TRADE, so the trade names the exit ════

class OandaReadsItsOwnTradeCloseTests(SimpleTestCase):

    def _t(self, payload, **meta):
        from bot_program.engine.oanda_client import OANDATrader
        c = OANDATrader("k", "101-1")
        sess = MagicMock()
        sess.get.return_value = _resp(payload)
        c._session = sess
        return c, _Trade(**meta)

    def test_a_closed_trade_gives_its_average_close(self):
        c, t = self._t({"trade": {"state": "CLOSED",
                                  "averageClosePrice": "1.08312",
                                  "initialUnits": "-10000"}},
                       protective_trade_id="9001")
        got = c.closing_fill(t)
        self.assertAlmostEqual(got["price"], 1.08312, places=6)
        self.assertEqual(got["qty"], 10000.0)

    def test_an_open_trade_has_no_exit_to_read(self):
        """The stop has not fired. There is nothing to price yet, and a
        number here would be an invention."""
        c, t = self._t({"trade": {"state": "OPEN",
                                  "averageClosePrice": None}},
                       protective_trade_id="9001")
        self.assertIsNone(c.closing_fill(t))

    def test_without_the_trade_handle_it_does_not_guess(self):
        """OANDA's SL/TP are not standalone orders, so there is no order id
        to fall back to."""
        c, t = self._t({}, protective_order_ids=["x"])
        self.assertIsNone(c.closing_fill(t))


# ═══ Reconciliation prefers the measurement ════════════════════════════

class ReconciliationAsksTheBrokerFirstTests(TestCase):

    def _trade(self, **meta):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user(f"rf_{len(meta)}_{id(meta)}",
                                        password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="RF", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("200"), status="OPEN",
            paper=False, metadata=meta, opened_at=timezone.now())

    def _close(self, trade, client):
        from bot_program.reconcile_asset import _close_as_orphan
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_as_orphan(trade)
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.get(pk=trade.pk)

    def test_a_broker_fill_beats_the_ticker(self):
        """The ticker would have said 195; the stop actually filled at
        189.42, and the five-dollar difference is the slippage the track
        record is supposed to record."""
        client = MagicMock()
        client.closing_fill.return_value = {"price": 189.42, "qty": 10.0,
                                            "source": "alpaca:order:sl1"}
        client.ticker.return_value = {"lastPrice": "195"}
        row = self._close(self._trade(protective_stop_id="sl1"), client)
        self.assertEqual(row.exit_price, Decimal("189.42"))

    def test_a_measured_exit_is_not_flagged_as_inferred(self):
        """Flagging a real fill as an estimate understates the one part of
        the track record that is not one."""
        client = MagicMock()
        client.closing_fill.return_value = {"price": 189.42, "qty": 10.0,
                                            "source": "s"}
        row = self._close(self._trade(protective_stop_id="sl1"), client)
        self.assertFalse(row.metadata.get("exit_price_inferred"))
        self.assertEqual(row.metadata.get("exit_fill_source"), "broker")

    def test_falling_back_to_the_ticker_is_still_flagged_inferred(self):
        client = MagicMock()
        client.closing_fill.return_value = None
        client.ticker.return_value = {"lastPrice": "195"}
        row = self._close(self._trade(), client)
        self.assertEqual(row.exit_price, Decimal("195"))
        self.assertTrue(row.metadata.get("exit_price_inferred"))
        self.assertEqual(row.metadata.get("exit_fill_source"), "mark")

    def test_a_client_with_no_closing_fill_still_reconciles(self):
        """Not every venue has one, and a missing method is not an error."""
        client = MagicMock(spec=["ticker", "get_positions"])
        client.ticker.return_value = {"lastPrice": "195"}
        row = self._close(self._trade(), client)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(row.exit_price, Decimal("195"))

    def test_a_broker_that_raises_costs_this_row_an_estimate_not_a_crash(self):
        client = MagicMock()
        client.closing_fill.side_effect = RuntimeError("socket gone")
        client.ticker.return_value = {"lastPrice": "195"}
        row = self._close(self._trade(), client)
        self.assertEqual(row.status, "CLOSED")
        self.assertTrue(row.metadata.get("exit_price_inferred"))

    def test_nothing_anywhere_still_means_unmeasured(self):
        client = MagicMock()
        client.closing_fill.return_value = None
        client.ticker.return_value = {}
        row = self._close(self._trade(), client)
        self.assertIsNone(row.pnl)
        self.assertTrue(row.metadata.get("exit_price_unavailable"))
