"""What the CLOSE_PENDING drain is allowed to do to a live position.

Two failures, both of them quiet.

**A scratch that never happened.** `_mark_price` answered with the trade's
ENTRY price whenever the ticker failed or returned nothing. Two callers book
that mark AS the exit price — the paths where the broker is already flat and
there is no fill to read — so a stop-out that cost real money was recorded as
exit == entry, pnl 0.00, 0.0R. The 24h daily-loss gate sums that loss as
nothing and the promotion track record counts a break-even trade that never
happened.

**Two live closes on one position.** The sweep read a plain queryset and
started closing: no row lock, and no look at the claim the CLOSE button
takes. The task is deliberately ungated, beat fires it every 300s onto a
queue with two worker slots, and one pass over a timing-out broker outruns
the beat — so two workers could walk the same rows. The module's only
anti-stacking device reads a metadata key written only AFTER a submit
returns, so while the first close is in flight there is nothing in the row
for the second caller to see. Both send a market order and the flatten
becomes a naked reverse position.

Run with:  python manage.py test tests.test_close_retry_truth
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="crt_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, asset_class="stock", name="CRT"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="live",
        symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
    )


def _pending(cfg, **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("100"), entry_price=Decimal("200"),
        stop_loss=Decimal("196"), take_profit=Decimal("210"),
        status="CLOSE_PENDING", paper=False,
    )
    defaults.update(kw)
    return AssetBotTrade.objects.create(**defaults)


class FlatBrokerBookingTests(TestCase):
    """The broker no longer holds the position: what price gets booked."""

    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def _flat_client(self, ticker):
        client = MagicMock()
        client.get_positions = MagicMock(return_value=[])
        client.ticker = ticker
        return client

    def test_a_stop_out_with_no_quote_is_not_booked_as_a_flat_scratch(self):
        trade = _pending(self.cfg)
        client = self._flat_client(
            MagicMock(side_effect=RuntimeError("TWS not responding")))

        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            from bot_program.pending_closes import retry_all_pending_closes
            out = retry_all_pending_closes()

        trade.refresh_from_db()
        self.assertEqual(out["closed"], 0)
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.exit_price)
        self.assertIsNone(trade.closed_at)
        # It counts as a failed attempt, so it escalates to the operator
        # instead of sitting silently.
        self.assertEqual(trade.metadata.get("close_retry_attempts"), 1)

    def test_a_zero_lastprice_is_not_a_price_either(self):
        trade = _pending(self.cfg)
        client = self._flat_client(
            MagicMock(return_value={"lastPrice": "0"}))

        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            from bot_program.pending_closes import retry_all_pending_closes
            retry_all_pending_closes()

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.exit_price)

    def test_a_flat_broker_with_a_real_quote_books_the_loss(self):
        trade = _pending(self.cfg)
        client = self._flat_client(
            MagicMock(return_value={"lastPrice": "195.50"}))

        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            from bot_program.pending_closes import retry_all_pending_closes
            out = retry_all_pending_closes()

        trade.refresh_from_db()
        self.assertEqual(out["closed"], 1)
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("195.50000000"))
        self.assertEqual(trade.pnl, Decimal("-450"))
        # No new order was sent at a broker that is already flat.
        client.market_order.assert_not_called()

    def test_no_mark_means_no_new_order_at_a_flat_broker(self):
        _pending(self.cfg)
        client = self._flat_client(MagicMock(return_value={}))

        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            from bot_program.pending_closes import retry_all_pending_closes
            retry_all_pending_closes()

        client.market_order.assert_not_called()


class SweepClaimTests(TestCase):
    """One close at a time per row, whoever is asking."""

    def setUp(self):
        self.user = _user("claim_u")
        self.cfg = _cfg(self.user, name="CLAIM")

    def _live_client(self):
        client = MagicMock()
        client.get_positions = MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "100"}])
        client.ticker = MagicMock(return_value={"lastPrice": "199"})
        client.market_order = MagicMock(return_value={
            "orderId": "9", "status": "FILLED",
            "executedQty": "100", "avgPrice": "199"})
        return client

    def _sweep(self, client):
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            from bot_program.pending_closes import retry_all_pending_closes
            return retry_all_pending_closes()

    def test_a_close_already_in_flight_is_not_closed_a_second_time(self):
        from bot_program.manual_close import CLAIM_KEY
        trade = _pending(self.cfg,
                         metadata={CLAIM_KEY: timezone.now().isoformat()})
        client = self._live_client()

        out = self._sweep(client)

        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(out["still_pending"], 1)
        self.assertEqual(out["closed"], 0)

    def test_a_claim_left_by_a_dead_worker_expires(self):
        from datetime import timedelta
        from bot_program.manual_close import CLAIM_KEY, CLAIM_TTL_SECONDS
        stale = (timezone.now()
                 - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        trade = _pending(self.cfg, metadata={CLAIM_KEY: stale})

        self._sweep(self._live_client())

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_the_sweep_drops_its_claim_when_it_is_done(self):
        """A claim left behind would lock the CLOSE button out of the row."""
        from bot_program.manual_close import CLAIM_KEY
        trade = _pending(self.cfg)
        client = self._live_client()
        client.market_order = MagicMock(side_effect=RuntimeError("still down"))

        self._sweep(client)

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertNotIn(CLAIM_KEY, trade.metadata or {})

    def test_the_row_is_claimed_while_the_close_is_in_flight(self):
        """The claim has to be visible to the OTHER worker before the order
        goes out — the working-order flag is written only afterwards, which
        is exactly the window two closes used to stack in."""
        from bot_program.manual_close import CLAIM_KEY
        from bot_program.models import AssetBotTrade
        trade = _pending(self.cfg)
        seen = {}

        client = self._live_client()

        def _submit(*a, **kw):
            row = AssetBotTrade.objects.get(pk=trade.pk)
            seen["claim"] = (row.metadata or {}).get(CLAIM_KEY)
            return {"orderId": "9", "status": "FILLED",
                    "executedQty": "100", "avgPrice": "199"}

        client.market_order = MagicMock(side_effect=_submit)
        self._sweep(client)

        self.assertTrue(seen.get("claim"),
                        "the row carried no claim while its close was live")
