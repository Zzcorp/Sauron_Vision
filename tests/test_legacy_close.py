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
        """A Binance FUTURES accept is status NEW with executedQty 0: an
        order the venue is WORKING, not a partial. It used to fall into the
        residual branch as "filled only 0 of N", which dropped the order id
        the next tick needs to withdraw it. It is recorded as resting, with
        its id, and the row stays OPEN."""
        trade = _row(market="futures")
        client = _client({"orderId": "o1", "status": "NEW",
                          "executedQty": "0"}, ensure_config=True)
        self.assertIs(_close(trade, 110, client), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertIn("close working:TP", trade.reason)
        self.assertIn("order o1", trade.reason)
        self.assertNotIn("close partial", trade.reason)

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


# ── a close the venue is still working ───────────────────────────────────────

WORKING = {"orderId": "555", "status": "WORKING", "working": True,
           "executedQty": "0", "avgPrice": "0"}
FILLED = {"orderId": "556", "status": "FILLED", "executedQty": "10",
          "avgPrice": "109"}


def _resting(trade, reason="SL", order_id="555", venue="ibkr"):
    """A row an earlier tick left with a close resting at the venue."""
    from bot_program.engine.runner import _append_reason
    _append_reason(trade, f"close working:{reason} (order {order_id} "
                          f"resting at {venue})")
    trade.save(update_fields=["reason"])
    return trade


class AWorkingCloseIsRestingNotPartial(TestCase):
    """IBKRTrader.market_order answers status WORKING / executedQty 0 with
    an orderId whenever the market close has not printed inside its
    one-second wait — a close sent outside regular hours, on a halted
    symbol, or simply not acked in time. `_close` read that 0 as "filled
    only 0 of N", dropped the order id, and its alert promised the venue
    would refuse the retry as a duplicate — which IBKR does not (orderRef
    buys traceability, not idempotency). The next hand-triggered tick then
    sent a SECOND full-size close: long N became short N at the open, and
    no row described the short."""

    def test_the_order_id_stays_on_the_row_and_the_alert_tells_the_truth(self):
        trade = _row(qty="30")
        client = _client(dict(WORKING))
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            self.assertIs(_close(trade, 95, client, "SL"), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertIn("close working:SL", trade.reason)
        self.assertIn("order 555", trade.reason)
        self.assertNotIn("close partial", trade.reason)
        from bot_program.engine.runner import _working_close
        self.assertEqual(_working_close(trade), ("SL", "555"))
        paged.assert_called_once()
        body = paged.call_args.kwargs["body"]
        self.assertIn("555", body)
        self.assertIn("withdraw", body)
        self.assertNotIn("refuses a duplicate", body)

    def test_a_retry_withdraws_the_resting_close_and_proves_it_first(self):
        """Tick 2: the stop is still crossed. The resting close is taken
        off the book, PROVED dead with nothing printed, and only then is
        the close sent again — one order resting at a time."""
        trade = _resting(_row(qty="31"))
        client = _client({**FILLED, "executedQty": "31"})
        client.cancel_order.return_value = True
        client.order_status.return_value = {"state": "dead", "filled": 0.0,
                                            "avgPrice": 0.0,
                                            "status": "Cancelled"}
        self.assertIs(_close(trade, 95, client, "SL"), True)
        client.cancel_order.assert_called_once_with("555")
        client.market_order.assert_called_once()
        names = [c[0] for c in client.mock_calls]
        self.assertLess(names.index("cancel_order"),
                        names.index("market_order"),
                        "the withdrawal must land before the resend")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("109"))
        self.assertIn("close withdrawn:SL", trade.reason)
        self.assertIn("closed:SL", trade.reason)

    def test_a_retry_that_cannot_prove_the_withdrawal_sends_nothing(self):
        trade = _resting(_row(qty="32"))
        client = _client(dict(FILLED))
        client.cancel_order.return_value = False
        client.order_status.return_value = {"state": "working",
                                            "filled": 0.0, "avgPrice": 0.0,
                                            "status": "PreSubmitted"}
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            self.assertIs(_close(trade, 95, client, "SL"), False)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("close blocked:SL", trade.reason)
        # The note is NOT retired: the next tick must still refuse.
        from bot_program.engine.runner import _working_close
        self.assertEqual(_working_close(trade), ("SL", "555"))
        self.assertIn("555", paged.call_args.kwargs["body"])

    def test_a_resting_close_that_filled_is_booked_off_its_fill_not_resent(self):
        """The cancel raced a fill. The position is flat at the venue, so
        sending another close would open the reverse position."""
        trade = _resting(_row(qty="33"))
        client = _client(dict(FILLED))
        client.cancel_order.return_value = False
        client.order_status.return_value = {"state": "filled",
                                            "filled": 33.0,
                                            "avgPrice": 94.5,
                                            "status": "Filled"}
        self.assertIs(_close(trade, 95, client, "SL"), True)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("94.5"))
        self.assertIn("exit:broker", trade.reason)
        self.assertIn("closed:SL", trade.reason)

    def test_a_partly_filled_resting_close_is_never_resent_at_full_size(self):
        trade = _resting(_row(qty="34"))
        client = _client(dict(FILLED))
        client.cancel_order.return_value = True
        client.order_status.return_value = {"state": "dead", "filled": 4.0,
                                            "avgPrice": 94.5,
                                            "status": "Cancelled"}
        self.assertIs(_close(trade, 95, client, "SL"), False)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("close partial:SL", trade.reason)
        self.assertIn("only 4", trade.reason)

    def test_a_client_that_cannot_withdraw_a_resting_close_sends_nothing(self):
        trade = _resting(_row(qty="35"))
        client = _client(dict(FILLED))
        del client.cancel_order
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            self.assertIs(_close(trade, 95, client, "SL"), False)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("close blocked:SL", trade.reason)
        self.assertIn("555", paged.call_args.kwargs["body"])

    def test_a_resting_close_with_no_id_blocks_the_retry(self):
        """The venue reported no id, so nothing can withdraw or poll it —
        and a resend beside it is exactly the double the note prevents."""
        trade = _resting(_row(qty="36"), order_id="?")
        client = _client(dict(FILLED))
        self.assertIs(_close(trade, 95, client, "SL"), False)
        client.market_order.assert_not_called()
        client.cancel_order.assert_not_called()

    def test_the_note_is_retired_by_a_close_and_survives_the_reason_cut(self):
        from bot_program.engine.runner import (_REASON_MAX, _append_reason,
                                               _working_close)
        trade = _resting(_row(qty="37"))
        # A week of blocked retries grows the column past its bound; the
        # cut must land on a note boundary or the resting note is lost and
        # the next tick resends.
        for _ in range(60):
            _append_reason(trade, "close blocked:SL (" + "x" * 40 + ")")
        self.assertLessEqual(len(trade.reason), _REASON_MAX)
        self.assertTrue(trade.reason.startswith("close "),
                        "the cut must not leave half a note")
        self.assertEqual(_working_close(trade), ("SL", "555"),
                         "the resting note must survive the cut")
        _append_reason(trade, "closed:SL")
        self.assertIsNone(_working_close(trade))


class TheTickPollsARestingClose(TestCase):
    """This lane has no drain: the hand-triggered tick is the poll. A close
    that printed since the last tick books the row off its fill; one that
    died with nothing filled retires the note so the SL/TP test may send
    afresh; one still working is left to `_close`, which withdraws it."""

    def _settle(self, trade, client):
        from bot_program.engine.runner import _settle_working_close
        return _settle_working_close(trade, client)

    def test_a_fill_since_the_last_tick_books_the_row(self):
        trade = _resting(_row(qty="40"), reason="TP")
        client = _client()
        client.order_status.return_value = {"state": "filled",
                                            "filled": 40.0,
                                            "avgPrice": 111.0,
                                            "status": "Filled"}
        self.assertIs(self._settle(trade, client), True)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("111"))
        self.assertIn("closed:TP", trade.reason)
        self.assertIn("exit:broker", trade.reason)

    def test_an_order_that_died_unfilled_retires_the_note(self):
        from bot_program.engine.runner import _working_close
        trade = _resting(_row(qty="41"))
        client = _client()
        client.order_status.return_value = {"state": "dead", "filled": 0.0,
                                            "avgPrice": 0.0,
                                            "status": "Cancelled"}
        self.assertIs(self._settle(trade, client), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("close cancelled:SL", trade.reason)
        self.assertIsNone(_working_close(trade))

    def test_an_order_still_working_is_left_resting(self):
        from bot_program.engine.runner import _working_close
        trade = _resting(_row(qty="42"))
        client = _client()
        client.order_status.return_value = {"state": "working",
                                            "filled": 0.0, "avgPrice": 0.0,
                                            "status": "PreSubmitted"}
        self.assertIs(self._settle(trade, client), False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(_working_close(trade), ("SL", "555"))

    def test_a_row_with_nothing_resting_is_not_polled(self):
        trade = _row(qty="43")
        client = _client()
        self.assertIs(self._settle(trade, client), False)
        client.order_status.assert_not_called()

    def test_the_manage_loop_books_a_filled_resting_close_before_the_sl_test(self):
        """End to end through run_bot_tick: the price is back inside the
        band, so nothing would have looked at this row again — and the
        account was flat while the row said OPEN."""
        trade = _resting(_row(qty="44"), reason="SL")
        cfg = trade.config
        cfg.enabled = True
        cfg.symbols = []
        cfg.save()
        client = _client()
        client.ticker.return_value = {"lastPrice": "100"}
        client.order_status.return_value = {"state": "filled",
                                            "filled": 44.0,
                                            "avgPrice": 94.0,
                                            "status": "Filled"}
        from bot_program.engine import runner
        with mock.patch.object(runner, "client_for_symbol",
                               return_value=client):
            runner.run_bot_tick(cfg.user_id)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("94"))
