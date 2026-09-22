"""THE LEGACY CLOSE BOOKED THE ROW BEFORE IT ASKED THE VENUE.

`runner._close` set status CLOSED, wrote an exit price off the MARK and
computed the P&L — all before sending anything — then sent the order inside a
try whose except only logged, and saved CLOSED regardless. A live legacy trade
whose close failed was booked CLOSED at a price nobody filled while the
position stayed open at the venue.

The lane has no Celery beat entry, but `bot/tick/` is `@login_required` and
`@require_POST` and calls it by hand, with no PIN and no component gate.

Every test below is a guard the FIRST version of the fix dropped. Three lenses
refuted that version fatally and converged on the same answer: reuse what
`kill_switch._close_legacy_trade` already does correctly on this same model,
rather than hand-roll it. The design's stated reason for not importing
`pending_closes` — "this model has none of their fields" — was false;
kill_switch imports four of its helpers and applies them to a BotTrade.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase


def _row(*, paper=False, market="spot", qty="10"):
    from bot_program.models import BotConfig, BotTrade
    user = User.objects.create_user(
        username="lc_%s_%s_%s" % (paper, market, qty), password="x")
    cfg = BotConfig.objects.create(
        user=user, capital_usdt=Decimal("1000"),
        mode="paper" if paper else "live", market_type=market)
    return BotTrade.objects.create(
        config=cfg, symbol="BTCUSDT", side="BUY", qty=Decimal(qty),
        entry_price=Decimal("100"), stop_loss=Decimal("95"),
        take_profit=Decimal("110"), paper=paper, status="OPEN")


def _client(response=None, *, raises=None, ensure_config=False):
    c = mock.MagicMock()
    if raises is not None:
        c.market_order = mock.MagicMock(side_effect=raises)
    else:
        c.market_order = mock.MagicMock(
            return_value=response if response is not None
            else {"orderId": "o1"})
    if not ensure_config:
        del c.ensure_config
    return c


def _close(trade, price, client, reason="TP"):
    from bot_program.engine.runner import _close as fn
    return fn(trade, Decimal(str(price)), client, reason)


class NothingIsWrittenBeforeTheVenueAnswers(TestCase):

    def test_a_refused_order_leaves_the_row_open(self):
        trade = _row()
        client = _client(raises=RuntimeError("insufficient balance"))
        self.assertIs(_close(trade, 110, client), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price,
                          "exit_price must stay NULL — five readers use it to "
                          "decide a row is still open")
        self.assertEqual(trade.pnl_usdt, Decimal("0"))
        self.assertIsNone(trade.closed_at)
        self.assertIn("close failed:TP", trade.reason)
        self.assertIn("insufficient balance", trade.reason)

    def test_a_live_row_routed_to_the_simulator_sends_nothing(self):
        """PaperTrader.market_order does not raise — it answers status FILLED
        at a simulated price, so booking it would stamp a fake fill on a real
        position. The entry path in the same file already refuses this."""
        from bot_program.engine.paper_trader import PaperTrader
        trade = _row()
        client = PaperTrader(trade.config)
        with mock.patch.object(PaperTrader, "market_order") as sent:
            self.assertIs(_close(trade, 110, client), False)
            sent.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertIn("close refused:TP", trade.reason)

    def test_a_paper_row_is_still_booked_off_the_mark(self):
        """Nothing is sent for a paper row, so there is nothing to wait for."""
        trade = _row(paper=True)
        client = _client()
        self.assertIs(_close(trade, 110, client), True)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("110"))
        self.assertEqual(trade.pnl_usdt, Decimal("100"))
        self.assertIn("exit:mark", trade.reason)


class TheExitIsTheFillWhenThereIsOne(TestCase):

    def test_a_reported_average_beats_the_mark_and_says_so(self):
        trade = _row()
        client = _client({"orderId": "o1", "avgPrice": "109.5",
                          "executedQty": "10"})
        self.assertIs(_close(trade, 110, client), True)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("109.5"))
        self.assertIn("exit:broker", trade.reason)

    def test_binance_spot_reports_no_average_and_the_ratio_is_used(self):
        """Spot returns the quote total and the base quantity; their ratio IS
        the average fill. Without that branch every live crypto exit would
        report the mark for ever."""
        trade = _row()
        client = _client({"orderId": "o1", "executedQty": "10",
                          "cummulativeQuoteQty": "1090"})
        self.assertIs(_close(trade, 110, client), True)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("109"))
        self.assertIn("exit:broker", trade.reason)

    def test_a_response_with_no_price_books_the_mark_and_says_so(self):
        trade = _row()
        client = _client({"orderId": "o1"})
        self.assertIs(_close(trade, 110, client), True)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("110"))
        self.assertIn("exit:mark", trade.reason)

    def test_a_zero_average_is_not_a_price(self):
        """PaperTrader answers avgPrice 0 for a symbol with no Instrument row,
        and the router's own comment says legacy symbols routinely have none."""
        trade = _row()
        client = _client({"orderId": "o1", "avgPrice": "0"})
        self.assertIs(_close(trade, 110, client), True)
        trade.refresh_from_db()
        self.assertEqual(trade.exit_price, Decimal("110"))
        self.assertIn("exit:mark", trade.reason)


class APartialFillHasNowhereToLive(TestCase):

    def test_a_residual_leaves_the_row_open(self):
        trade = _row()
        client = _client({"orderId": "o1", "avgPrice": "109",
                          "executedQty": "3"})
        self.assertIs(_close(trade, 110, client), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertIn("close partial:TP", trade.reason)
        self.assertIn("only 3", trade.reason)

    def test_an_accepted_but_unfilled_order_is_not_a_close(self):
        """A Binance FUTURES accept is status NEW with executedQty 0. No
        separate branch is needed: a reported 0 means "nothing gone yet, the
        position is live", which the residual check already catches."""
        trade = _row(market="futures")
        client = _client({"orderId": "o1", "status": "NEW",
                          "executedQty": "0"}, ensure_config=True)
        self.assertIs(_close(trade, 110, client), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("close partial:TP", trade.reason)

    def test_a_full_fill_inside_dust_still_closes(self):
        trade = _row()
        client = _client({"orderId": "o1", "avgPrice": "109",
                          "executedQty": "10"})
        self.assertIs(_close(trade, 110, client), True)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")


class TheOrderCarriesANameTheVenueCanRefuseTwice(TestCase):

    def _sent_kwargs(self, trade, reason="TP", **kw):
        client = _client(**kw)
        _close(trade, 110, client, reason)
        return client.market_order.call_args.kwargs

    def test_the_close_is_stamped_with_a_deterministic_id(self):
        """Anonymous was the defect: leaving the row OPEN means the next tick
        re-sends, and on OANDA or Alpaca a second full-size order opens the
        reverse position."""
        first = self._sent_kwargs(_row(qty="10"))
        self.assertTrue(first["client_order_id"].startswith("sv-"))

    def test_the_same_trade_and_intent_reuse_the_same_id(self):
        from bot_program.engine.idempotency import make_client_order_id
        trade = _row(qty="11")
        sent = self._sent_kwargs(trade)
        self.assertEqual(sent["client_order_id"], make_client_order_id(
            config_id=trade.config_id, symbol="BTCUSDT",
            signal_id=str(trade.id), intent="TP"))

    def test_a_stop_and_a_target_are_different_logical_orders(self):
        trade_a, trade_b = _row(qty="12"), _row(qty="13")
        # Same row cannot be closed twice, so two rows with the same shape.
        tp = self._sent_kwargs(trade_a, "TP")["client_order_id"]
        sl = self._sent_kwargs(trade_b, "SL")["client_order_id"]
        self.assertNotEqual(tp, sl)

    def test_a_kill_switch_flatten_is_not_refused_as_a_duplicate(self):
        """Different logical orders must carry different names, or the venue
        would refuse the emergency flatten as a copy of the TP close."""
        from bot_program.engine.kill_switch import _kill_order_id
        trade = _row(qty="14")
        tp = self._sent_kwargs(trade, "TP")["client_order_id"]
        self.assertNotEqual(tp, _kill_order_id(trade))

    def test_reduce_only_survives_for_a_futures_config(self):
        """It rode on the old code path and must not be lost to the move:
        without it a close into an already-flat futures account opens the
        reverse position."""
        sent = self._sent_kwargs(_row(market="futures", qty="15"),
                                 ensure_config=True)
        self.assertTrue(sent.get("reduce_only"))

    def test_reduce_only_is_not_sent_to_a_spot_client(self):
        self.assertNotIn("reduce_only", self._sent_kwargs(_row(qty="16")))


class AVenueThatCannotNetAnOppositeOrderIsRefused(TestCase):

    def test_a_close_that_would_open_a_second_position_sends_nothing(self):
        """eToro's market_order only ever OPENS — a SELL is sellShort. The
        router checks the Saxo/eToro/IBKR overrides BEFORE asset-class
        routing, so a legacy BotTrade really can be handed one."""
        trade = _row(qty="17")
        client = _client()
        client.close_needs_position_id = mock.MagicMock(return_value=True)
        del client.close_position
        self.assertIs(_close(trade, 110, client), False)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertIn("close failed:TP", trade.reason)


class TheOperatorIsToldOnceAndPointedSomewhere(TestCase):

    def test_the_alert_names_the_trade_and_the_kill_switch(self):
        trade = _row(qty="18")
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            _close(trade, 110, _client(raises=RuntimeError("nope")))
        paged.assert_called_once()
        kwargs = paged.call_args.kwargs
        self.assertIn(str(trade.id), kwargs["title"])
        self.assertIn("BTCUSDT", kwargs["title"])
        self.assertEqual(kwargs["cooldown_hours"], 24)
        self.assertIn("FLATTEN", kwargs["body"])

    def test_a_failed_alert_does_not_cost_the_close(self):
        trade = _row(qty="19")
        with mock.patch("bot_program.notifications.notify_staff",
                        side_effect=RuntimeError("no mailer")):
            self.assertIs(_close(trade, 110, _client(raises=OSError("x"))),
                          False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_the_reason_column_is_bounded(self):
        """A row an operator leaves alone for a week must not grow it without
        bound; the tail is what matters."""
        from bot_program.engine.runner import _REASON_MAX
        trade = _row(qty="20")
        trade.reason = "x" * (_REASON_MAX + 500)
        trade.save(update_fields=["reason"])
        _close(trade, 110, _client(raises=RuntimeError("nope")))
        trade.refresh_from_db()
        self.assertLessEqual(len(trade.reason), _REASON_MAX)
        self.assertIn("close failed:TP", trade.reason)
