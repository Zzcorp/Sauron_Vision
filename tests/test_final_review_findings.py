"""Regressions for what the pre-commit review caught.

Three defects, all introduced by the change set they were found in, and all
on paths that move real money.

Run with:  python manage.py test tests.test_final_review_findings
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _user(name="frf_u"):
    return get_user_model().objects.create_user(name, password="x")


def _cfg(user, asset_class="stock"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name="frf", enabled=True,
        mode="live", symbols=["AAPL"], capital=Decimal("100000"))


def _pending(cfg, **meta):
    """A LIVE row mid-close, in the state the exit booker leaves it."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        status="CLOSE_PENDING", paper=False, metadata=meta)


class ReconciliationSurvivesTheNextBookingTests(TestCase):
    """`close_fills` is the ledger and `close_filled_qty` is a sum of it.

    `resolve_exit_fill` RE-DERIVES the cumulative fill by adding the slices
    up, so a reconciliation that corrected only the cached total was thrown
    away by the very next booking — and the phantom residual it had just
    removed came straight back, to be re-sold.
    """

    def setUp(self):
        self.trade = _pending(_cfg(_user()),
                              close_fills=[{"qty": "4", "price": "99",
                                            "source": "broker"}],
                              close_filled_qty="4",
                              close_residual_qty="6")

    def _client(self, remaining):
        client = MagicMock()
        client.get_positions = MagicMock(
            return_value=[{"symbol": "AAPL", "qty": str(remaining)}])
        client.ticker = MagicMock(return_value={"lastPrice": "98"})
        return client

    def test_the_revision_is_written_into_the_ledger(self):
        from bot_program.pending_closes import _reconcile_filled_against_broker
        # Broker says 3 left of 10 → 7 filled, up from the recorded 4.
        _reconcile_filled_against_broker(self.trade, self._client(3))
        self.trade.refresh_from_db()
        total = sum(Decimal(f["qty"])
                    for f in self.trade.metadata["close_fills"])
        self.assertEqual(total, Decimal("7"))
        self.assertEqual(self.trade.metadata["close_filled_qty"], "7")

    def test_the_next_booking_agrees_with_the_reconciliation(self):
        """The actual defect: re-derivation must not undo the correction."""
        from bot_program.pending_closes import (
            _reconcile_filled_against_broker, resolve_exit_fill,
        )
        _reconcile_filled_against_broker(self.trade, self._client(3))
        self.trade.refresh_from_db()
        # A booking that adds nothing new must still see 7 already filled.
        fill = resolve_exit_fill(self.trade, None, mark=Decimal("98"))
        self.assertEqual(Decimal(fill["metadata"]["close_filled_qty"]),
                         Decimal("10"))
        self.assertTrue(fill["complete"])

    def test_reconciled_units_do_not_claim_a_broker_price(self):
        """They printed while nobody was looking, so the blended exit is a
        mark exit — it must not inherit `broker` provenance."""
        from bot_program.pending_closes import (
            _reconcile_filled_against_broker, resolve_exit_fill,
        )
        _reconcile_filled_against_broker(self.trade, self._client(3))
        self.trade.refresh_from_db()
        fill = resolve_exit_fill(self.trade, None, mark=Decimal("98"))
        self.assertEqual(fill["metadata"]["exit_fill_source"], "mark")

    def test_a_broker_reading_below_our_record_is_ignored(self):
        """Settlement lag must never talk us into re-selling what we sold."""
        from bot_program.pending_closes import _reconcile_filled_against_broker
        _reconcile_filled_against_broker(self.trade, self._client(9))
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.metadata["close_filled_qty"], "4")
        self.assertEqual(len(self.trade.metadata["close_fills"]), 1)

    def test_an_unreadable_book_changes_nothing(self):
        from bot_program.pending_closes import _reconcile_filled_against_broker
        client = MagicMock()
        client.get_positions = MagicMock(side_effect=RuntimeError("down"))
        _reconcile_filled_against_broker(self.trade, client)
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.metadata["close_filled_qty"], "4")


class KillSwitchDoesNotStackACloseTests(TestCase):
    """CLOSE_PENDING now means two things, and only one is safe to send an
    order on top of.

    It used to mean the broker REJECTED the close — nothing live. The exit
    work added "the broker ACCEPTED it and it has not printed yet", and on
    that row a second market order is a second live close for one position.
    Worse, an accepted-but-unprinted close reports zero filled, so the
    residual is the FULL position and the second order is full size.
    """

    def setUp(self):
        self.user = _user("frf_ks")
        self.trade = _pending(_cfg(self.user),
                              close_order_working=True,
                              close_working_order_id="abc",
                              close_filled_qty="0")

    def _run(self, client):
        from bot_program.engine.kill_switch import execute_kill_switch
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return execute_kill_switch(user=self.user, reason="test")

    def test_an_uncancellable_working_close_is_not_stacked_on(self):
        client = MagicMock()
        client.cancel_order = MagicMock(return_value=False)
        client.ticker = MagicMock(return_value={"lastPrice": "98"})
        res = self._run(client)
        client.market_order.assert_not_called()
        self.assertEqual(res["asset_positions_closed"], 0)
        self.assertEqual(len(res["errors"]), 1)

    def test_the_operator_is_told_the_position_may_still_be_open(self):
        client = MagicMock()
        client.cancel_order = MagicMock(return_value=False)
        client.ticker = MagicMock(return_value={"lastPrice": "98"})
        self.assertIn("still working", self._run(client)["errors"][0])

    def test_a_cancellable_one_is_flattened_normally(self):
        """The guard must not stop the kill switch doing its job."""
        client = MagicMock()
        client.cancel_order = MagicMock(return_value=True)
        client.ticker = MagicMock(return_value={"lastPrice": "98"})
        client.get_positions = MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "10"}])
        client.market_order = MagicMock(
            return_value={"status": "FILLED", "avgPrice": "98",
                          "executedQty": "10"})
        res = self._run(client)
        client.market_order.assert_called_once()
        self.assertEqual(res["asset_positions_closed"], 1)

    def test_a_close_that_finishes_during_the_cancel_sends_nothing(self):
        """Sending a zero-size order is how a flatten becomes an entry."""
        client = MagicMock()
        client.cancel_order = MagicMock(return_value=True)
        client.ticker = MagicMock(return_value={"lastPrice": "98"})
        client.get_positions = MagicMock(return_value=[])  # already flat
        res = self._run(client)
        client.market_order.assert_not_called()
        self.assertEqual(res["asset_positions_closed"], 1)


class MigrationMovesExistingBooksTests(SimpleTestCase):
    """An AlterField moves the DEFAULT, which only reaches rows created after
    it — so every deployed book would have kept the old ceiling and had the
    newly-armed gate refuse the platform's own default entry."""

    def _migration(self):
        import importlib
        return importlib.import_module(
            "portfolio.migrations.0011_single_position_default_agrees_with_sizing")

    def test_it_carries_a_data_step_and_not_only_a_field_change(self):
        from django.db import migrations as dj
        ops = self._migration().Migration.operations
        self.assertTrue(any(isinstance(o, dj.RunPython) for o in ops),
                        "the default moved but no existing row would follow")

    def test_the_data_step_is_reversible(self):
        from django.db import migrations as dj
        run = next(o for o in self._migration().Migration.operations
                   if isinstance(o, dj.RunPython))
        self.assertIsNotNone(run.reverse_code)

    def test_it_only_moves_the_untouched_default(self):
        """A migration that overwrites a risk limit somebody typed is a worse
        bug than the one it fixes."""
        import inspect
        src = inspect.getsource(self._migration())
        self.assertIn("max_single_position_pct=frm", src)
