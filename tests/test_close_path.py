"""The close path, between "the engine decides" and "the row says CLOSED".

Designed and refuted by a fleet of readers over the real code; every test
here is a failure one of them proved reachable, and several are failures the
FIRST draft of the fix would itself have shipped.

THE CLOCK EXIT WAS BEHIND THE MARK GATE

manage_positions read the mark and skipped the whole position when it was
unusable, and SaxoTrader.ticker answers lastPrice 0 for Saxo's NoAccess —
which is every CFD on a demo account not linked to a funded live one. So on
exactly those positions the time stop, the one exit the broker knows nothing
about, could never fire: they were held for ever, in silence. It compares
CLOCKS, so it now runs above the gate; everything that compares against a
price stays below it.

AND A CLOCK EXIT WOULD HAVE DOUBLED AN IN-DOUBT CLOSE

A row whose close request never came back carries close_in_doubt, and the
whole point of that marker is that a second close turns a closed long into a
full-size short. The clock does not care — it would have fired on every pass.
So the close now RESOLVES the doubt before it sends anything: flat means the
first close landed and nothing is sent; still held means it did not, so the
marker goes and the close proceeds; and "cannot say" sends nothing at all.

THE RETRY LOOP COULD NEVER CONCLUDE FLAT

Its safety valve was "is this symbol in the book", with no side and no size.
Under FifoEndOfDay the closing lot sits Open beside the lot it closed until
the evening netting, so the answer was "still held" all day, and the size came
off whichever lot the venue listed first — which can be the closing one.
remaining then equalled the whole position, nothing counted as filled, and a
third full-size market order went out: original long, closing short, retry
short, net short one full size, with the row stamped CLOSED at the third fill.

The reading is now netted per side in three states, and it is deliberately
timid about the difference between UNMEASURED (fall back to the row's own
arithmetic, as before) and AMBIGUOUS (an offsetting lot, or a sibling row
claiming the same units — send nothing at all).
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from tests.test_exit_truth import _cfg, _client, _trade, _user


def _tick(cfg, *, price="101", raises=False):
    """One manage_positions pass, with a mark the test chooses."""
    from bot_program.asset_engine.stock_bot import StockBot
    client = mock.MagicMock()
    if raises:
        client.ticker = mock.MagicMock(side_effect=RuntimeError("no session"))
    else:
        client.ticker = mock.MagicMock(return_value={"lastPrice": price})
    client.market_order = mock.MagicMock(
        return_value={"status": "FILLED", "avgPrice": "97",
                      "executedQty": "10"})
    client.get_positions = mock.MagicMock(return_value=[])
    with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
        out = StockBot(cfg).manage_positions()
    return out, client


def _stale(cfg, **meta):
    """An OPEN row whose holding ceiling is long past."""
    trade = _trade(cfg, metadata={"initial_stop_loss": 98.0, **meta})
    trade.opened_at = timezone.now() - timezone.timedelta(days=400)
    trade.save(update_fields=["opened_at"])
    return trade


class TheClockExitRunsWithoutAMarkTests(TestCase):

    def setUp(self):
        self.user = _user("clock_u")
        self.cfg = _cfg(self.user, name="CLOCK")
        self.cfg.extras = {**(self.cfg.extras or {}), "max_hold_days": 5}
        self.cfg.save(update_fields=["extras"])

    def test_a_position_the_broker_prices_at_zero_still_times_out(self):
        """Saxo's NoAccess answer IS lastPrice 0, on every CFD of an unlinked
        demo account. Behind the gate those positions were held for ever."""
        trade = _stale(self.cfg)
        _out, client = _tick(self.cfg, price="0")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        client.market_order.assert_called_once()

    def test_the_row_says_the_decision_had_no_mark(self):
        """A statement about the DECISION, which stays true for ever — not
        about the fill, which the broker may report a second later."""
        trade = _stale(self.cfg)
        _tick(self.cfg, price="0")
        trade.refresh_from_db()
        self.assertTrue(trade.metadata.get("time_stop_unpriced"))

    def test_a_priced_position_carries_no_such_flag(self):
        trade = _stale(self.cfg)
        _tick(self.cfg, price="101")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertNotIn("time_stop_unpriced", trade.metadata)

    def test_a_ticker_that_raises_does_not_stop_the_clock(self):
        """The read used to land in the loop's own handler and skip the
        position whole — killing the clock exit for the very reason it
        exists."""
        trade = _stale(self.cfg)
        _tick(self.cfg, raises=True)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_a_fresh_unpriced_position_is_left_open(self):
        """The reorder must not close anything the clock does not."""
        trade = _trade(self.cfg, metadata={"initial_stop_loss": 98.0})
        _tick(self.cfg, price="0")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_the_unpriced_skip_reaches_the_ledger(self):
        """`skips` is not a module-level name in base.py, so the record()
        added with the loud branch raised NameError into its own bare except:
        loud in the log, silent on the page the operator reads."""
        from bot_program.asset_engine import skips
        _trade(self.cfg, metadata={"initial_stop_loss": 98.0})
        _tick(self.cfg, price="0")
        self.cfg.refresh_from_db()
        self.assertIn(skips.NO_PRICE, str(self.cfg.extras or {}))


class AnInDoubtCloseIsResolvedNotRepeatedTests(TestCase):

    def setUp(self):
        self.user = _user("doubt_u")
        self.cfg = _cfg(self.user, name="DOUBT")

    def _close(self, trade, client):
        from bot_program.asset_engine.stock_bot import StockBot
        return StockBot(self.cfg)._close_trade(trade, Decimal("98"), client,
                                               reason="TIME")

    def _row(self):
        return _trade(self.cfg, metadata={
            "initial_stop_loss": 98.0,
            "close_in_doubt": {"reference": "EXIT-9", "at":
                               timezone.now().isoformat()}})

    def test_a_flat_broker_means_it_landed_and_nothing_is_sent(self):
        trade = self._row()
        client = _client({"status": "FILLED"}, last="98")
        client.get_positions = mock.MagicMock(return_value=[])
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR") as cm:
            self.assertFalse(self._close(trade, client))
        client.market_order.assert_not_called()
        self.assertTrue(any("DID land" in m for m in cm.output))

    def test_a_broker_that_still_holds_it_means_it_did_not_land(self):
        trade = self._row()
        client = _client({"status": "FILLED", "avgPrice": "98",
                          "executedQty": "10"}, last="98")
        client.get_positions = mock.MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "10", "side": "BUY"}])
        with self.assertLogs("bot_program.asset_engine.base", level="WARNING"):
            self._close(trade, client)
        client.market_order.assert_called_once()
        trade.refresh_from_db()
        self.assertNotIn("close_in_doubt", trade.metadata)
        self.assertIn("close_in_doubt_resolved", trade.metadata)

    def test_a_book_that_cannot_be_read_sends_nothing(self):
        """"Could not ask" is not proof of either, and an unresolvable doubt
        that sends anyway is the double close the marker exists to prevent."""
        trade = self._row()
        client = _client({"status": "FILLED"}, last="98")
        client.get_positions = mock.MagicMock(
            side_effect=RuntimeError("429 rate limited"))
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            self.assertFalse(self._close(trade, client))
        client.market_order.assert_not_called()
        paged.assert_called_once()
        trade.refresh_from_db()
        self.assertIn("close_doubt_alerted_at", trade.metadata)

    def test_the_alert_does_not_repeat_every_tick(self):
        trade = self._row()
        client = _client({"status": "FILLED"}, last="98")
        client.get_positions = mock.MagicMock(side_effect=RuntimeError("429"))
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            self._close(trade, client)
            trade.refresh_from_db()
            self._close(trade, client)
        self.assertEqual(paged.call_count, 1)

    def test_a_paper_row_is_unaffected(self):
        """Nothing is live at a broker, so there is no doubt to resolve."""
        trade = _trade(self.cfg, paper=True, metadata={
            "initial_stop_loss": 98.0,
            "close_in_doubt": {"reference": "X", "at":
                               timezone.now().isoformat()}})
        client = _client({"status": "FILLED"}, last="98")
        self.assertTrue(self._close(trade, client))


class TheBookIsReadInThreeStatesTests(TestCase):

    def setUp(self):
        self.user = _user("expo_u")
        self.cfg = _cfg(self.user, name="EXPO")

    def _read(self, rows, **meta):
        from bot_program.pending_closes import broker_exposure
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0, **meta})
        client = mock.MagicMock()
        client.get_positions = mock.MagicMock(return_value=rows)
        return broker_exposure(trade, client), trade

    def test_one_lot_on_our_side_is_held_with_its_size(self):
        out, _ = self._read([{"symbol": "AAPL", "qty": "7", "side": "BUY"}])
        self.assertEqual(out["state"], "held")
        self.assertEqual(out["qty"], Decimal("7"))

    def test_one_lot_needs_no_side_at_all(self):
        """Most feeds sign the quantity instead of naming a side, and a lone
        lot has nothing to offset — demanding a side read an ordinary book as
        unmeasured and stopped the reconciliation."""
        out, _ = self._read([{"symbol": "AAPL", "qty": "7"}])
        self.assertEqual(out["state"], "held")
        self.assertEqual(out["qty"], Decimal("7"))

    def test_an_empty_book_is_flat_and_that_is_a_measurement(self):
        out, _ = self._read([])
        self.assertEqual(out["state"], "flat")
        self.assertEqual(out["qty"], Decimal(0))

    def test_both_sides_open_is_ambiguous_and_never_a_number(self):
        """THE FINDING. Under FifoEndOfDay the closing lot sits Open beside
        the lot it closed all day, and netting it to a number hands a market
        order a size nobody measured."""
        out, _ = self._read([{"symbol": "AAPL", "qty": "10", "side": "BUY"},
                             {"symbol": "AAPL", "qty": "10", "side": "SELL"}])
        self.assertEqual(out["state"], "unknown")
        self.assertIsNone(out["qty"])
        self.assertTrue(out["ambiguous"])
        self.assertIn("OTHER side", out["why"])

    def test_an_unmeasured_lot_on_the_other_side_is_ambiguous_too(self):
        """Read as nothing it would leave the offsetting total at 0 while a
        real opposing position is open."""
        out, _ = self._read([{"symbol": "AAPL", "qty": "10", "side": "BUY"},
                             {"symbol": "AAPL", "side": "SELL"}])
        self.assertEqual(out["state"], "unknown")
        self.assertTrue(out["ambiguous"])

    def test_a_short_row_signed_by_its_quantity_is_the_other_side(self):
        out, _ = self._read([{"symbol": "AAPL", "qty": "-10"}])
        self.assertEqual(out["state"], "unknown")
        self.assertTrue(out["ambiguous"])

    def test_an_alpaca_long_is_our_side(self):
        out, _ = self._read([{"symbol": "AAPL", "qty": "4", "side": "long"}])
        self.assertEqual(out["state"], "held")
        self.assertEqual(out["qty"], Decimal("4"))

    def test_an_unreadable_book_is_unknown_and_not_flat(self):
        from bot_program.pending_closes import broker_exposure
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        client = mock.MagicMock()
        client.get_positions = mock.MagicMock(side_effect=RuntimeError("500"))
        out = broker_exposure(trade, client)
        self.assertEqual(out["state"], "unknown")
        self.assertIsNone(out["qty"])

    def test_an_option_under_the_same_symbol_is_not_this_position(self):
        out, _ = self._read([{"symbol": "AAPL", "qty": "3", "side": "BUY",
                              "sec_type": "OPT"}])
        self.assertEqual(out["state"], "flat")

    def test_a_sibling_row_makes_the_size_unattributable(self):
        """The account total cannot say whose units are whose, and a resubmit
        sized off it would sell units belonging to another row."""
        from bot_program.pending_closes import broker_exposure
        mine = _trade(self.cfg, status="CLOSE_PENDING",
                      metadata={"initial_stop_loss": 98.0})
        _trade(self.cfg, status="OPEN", metadata={"initial_stop_loss": 98.0})
        client = mock.MagicMock()
        client.get_positions = mock.MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "20", "side": "BUY"}])
        out = broker_exposure(mine, client)
        self.assertEqual(out["state"], "unknown")
        self.assertTrue(out["ambiguous"])
        self.assertIn("another live row", out["why"])

    def test_presence_without_a_number_falls_back_rather_than_blocking(self):
        """Unmeasured is not ambiguous: the size comes from the row's own
        arithmetic, exactly as it did before the reader could net."""
        from bot_program.pending_closes import broker_position_qty
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        client = mock.MagicMock()
        client.get_positions = mock.MagicMock(
            return_value=[{"symbol": "AAPL", "market_value": "900"},
                          {"symbol": "AAPL", "market_value": "100"}])
        self.assertIsNone(broker_position_qty(trade, client))


class TheRetryLoopRefusesToStackACloseTests(TestCase):

    def setUp(self):
        self.user = _user("stack_u")
        self.cfg = _cfg(self.user, name="STACK")

    def test_an_unknown_status_is_in_doubt_and_a_filled_one_is_not(self):
        from bot_program.pending_closes import order_in_doubt
        self.assertTrue(order_in_doubt({"status": "UNKNOWN"}))
        self.assertTrue(order_in_doubt({"inDoubt": True, "status": ""}))
        self.assertFalse(order_in_doubt({"status": "FILLED"}))
        self.assertFalse(order_in_doubt(None))

    def test_a_202_marks_the_row_where_the_answer_arrives(self):
        from bot_program.pending_closes import (CLOSE_IN_DOUBT_KEY,
                                                resolve_exit_fill)
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        fill = resolve_exit_fill(trade, {"status": "UNKNOWN", "orderId": "77",
                                         "executedQty": "0"},
                                mark=Decimal("98"))
        self.assertIn(CLOSE_IN_DOUBT_KEY, fill["metadata"])
        self.assertEqual(fill["metadata"][CLOSE_IN_DOUBT_KEY]["order_id"],
                         "77")

    def test_a_marked_row_sends_nothing_and_spends_no_budget(self):
        """The cancel-and-resend path cannot help: a cancel proves nothing
        about an order the venue never admitted holding."""
        from bot_program.pending_closes import retry_trade_close
        trade = _trade(self.cfg, status="CLOSE_PENDING", metadata={
            "initial_stop_loss": 98.0,
            "close_in_doubt": {"order_id": "77", "reference": "EXIT-7",
                               "at": timezone.now().isoformat()}})
        client = _client({"status": "FILLED"}, last="98")
        client.get_positions = mock.MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "10", "side": "BUY"}])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            self.assertFalse(retry_trade_close(trade))
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIn("may already be live",
                      trade.metadata["close_blocked_why"])
        self.assertNotIn("close_retry_attempts", trade.metadata)

    def test_an_ambiguous_book_sends_nothing(self):
        from bot_program.pending_closes import retry_trade_close
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        client = _client({"status": "FILLED"}, last="98")
        client.get_positions = mock.MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "10", "side": "BUY"},
                          {"symbol": "AAPL", "qty": "10", "side": "SELL"}])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            self.assertFalse(retry_trade_close(trade))
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertIn("OTHER side", trade.metadata["close_blocked_why"])

    def test_a_flat_book_still_finalises_without_an_order(self):
        from bot_program.pending_closes import retry_trade_close
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0,
                                 "close_in_doubt": {"reference": "X", "at":
                                                    timezone.now().isoformat()}})
        client = _client({"status": "FILLED"}, last="97")
        client.get_positions = mock.MagicMock(return_value=[])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            retry_trade_close(trade)
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_a_blocked_row_says_so_once_an_hour_not_every_pass(self):
        from bot_program.pending_closes import _note_close_blocked
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        with self.assertLogs("bot_program.pending_closes", level="ERROR"):
            _note_close_blocked(trade, "because")
        trade.refresh_from_db()
        first = trade.metadata["close_blocked_logged_at"]
        _note_close_blocked(trade, "because")
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["close_blocked_logged_at"], first)
        self.assertEqual(trade.metadata["close_blocked_passes"], 2)


# ── the close a venue actually understands ──────────────────────────────

class EtoroClosesByPositionIdOrNotAtAllTests(TestCase):
    """EtoroTrader.market_order sends {"action": "open", ...} and has no close
    branch, so the engine's "opposite market order" OPENED a short beside the
    long: the row booked CLOSED at that fill while the account held DOUBLE,
    hedged, paying both spreads. Every exit did it — stop-out, take-profit,
    clock exit, the operator's own close, the kill switch, the retry drain."""

    def setUp(self):
        self.user = _user("etclose_u")
        self.cfg = _cfg(self.user, name="ETCLOSE")

    def test_the_adapter_says_an_opposite_order_would_not_close(self):
        from bot_program.engine.etoro_client import EtoroTrader
        self.assertIs(EtoroTrader("k", "u", env="demo")
                      .close_needs_position_id(), True)

    def test_the_adapter_reports_its_position_id_on_every_fill(self):
        """Not only beside an accepted bracket: a handle that exists only when
        eToro accepted a stop is a handle missing on exactly the rows whose
        stop it refused — and at this venue no handle means no close."""
        import inspect

        from bot_program.engine.etoro_client import EtoroTrader
        src = inspect.getsource(EtoroTrader.market_order)
        head = src.split('if protected and filled_units > 0 and position_id:')[0]
        self.assertIn('out["positionId"] = str(position_id)', head)

    def test_the_engine_stores_the_handle_the_close_needs(self):
        import ast
        import inspect
        import textwrap

        from bot_program.asset_engine.base import AssetBot
        # The handle is stamped by AssetBot.venue_stamps (shared with the
        # TAKE TRADE lane); the keys are read off the helper and the call
        # off execute_entry below.
        src = textwrap.dedent(inspect.getsource(AssetBot.venue_stamps))
        keys = {n.slice.value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Subscript)
                and isinstance(getattr(n, "slice", None), ast.Constant)
                and isinstance(n.value, ast.Name)
                and n.value.id == "stamps"
                and isinstance(n.slice.value, str)}
        self.assertIn("broker_position_id", keys)
        entry = textwrap.dedent(inspect.getsource(AssetBot.execute_entry))
        called = {n.func.attr for n in ast.walk(ast.parse(entry))
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        self.assertIn("venue_stamps", called)

    def _etoro_like(self):
        client = mock.MagicMock(spec=["market_order", "close_position",
                                      "close_needs_position_id", "ticker"])
        client.close_needs_position_id.return_value = True
        client.close_position.return_value = {"orderId": "c1",
                                              "status": "PENDING"}
        client.ticker.return_value = {"lastPrice": "98"}
        return client

    def test_the_close_goes_through_the_position_endpoint(self):
        from bot_program.engine.venue_close import close_or_refuse
        trade = _trade(self.cfg, metadata={"broker_position_id": "P77"})
        client = self._etoro_like()
        close_or_refuse(trade, client, 10.0, close_side="SELL",
                        client_order_id="EXIT-1")
        client.close_position.assert_called_once()
        self.assertEqual(client.close_position.call_args.args[0], "P77")
        client.market_order.assert_not_called()

    def test_with_no_handle_nothing_is_sent_at_all(self):
        from bot_program.engine.venue_close import close_or_refuse
        trade = _trade(self.cfg, metadata={})
        client = self._etoro_like()
        with self.assertLogs("bot_program.engine.venue_close", level="ERROR"):
            with self.assertRaises(RuntimeError):
                close_or_refuse(trade, client, 10.0, close_side="SELL")
        client.market_order.assert_not_called()
        client.close_position.assert_not_called()

    def test_a_close_at_a_venue_that_did_not_carry_the_row_is_refused(self):
        """The stamp steers the SEND, not only reconcile's refusal: a moved
        primary-for flag must not turn a close into an opening order at the
        other venue. Same-named stubs of test_venue_drift — the class NAME
        is what adapter_key reads; nothing is subclassed."""
        from bot_program.engine.venue_close import close_or_refuse
        from tests.test_venue_drift import IBKRTrader as IBKRBook
        trade = _trade(self.cfg, metadata={"broker": "etoro",
                                           "broker_position_id": "P77"})
        with self.assertLogs("bot_program.engine.venue_close", level="ERROR"):
            with self.assertRaises(RuntimeError):
                close_or_refuse(trade, IBKRBook(), 10.0, close_side="SELL")

    def test_the_carrying_venue_still_closes_and_an_unmapped_client_is_not_refused(self):
        from bot_program.engine.venue_close import close_or_refuse
        from tests.test_venue_drift import EtoroTrader as EtoroBook
        trade = _trade(self.cfg, metadata={"broker": "etoro",
                                           "broker_position_id": "P77"})
        book = EtoroBook()                      # class name "EtoroTrader"
        book.close_needs_position_id = lambda: True
        book.close_position = mock.MagicMock(return_value={"status": "PENDING"})
        close_or_refuse(trade, book, 10.0, close_side="SELL")
        self.assertEqual(book.close_position.call_args.args[0], "P77")
        # A MagicMock's class is not in the map: "" refuses nothing, which
        # is why every older test in this class still passes unchanged.
        client = self._etoro_like()
        close_or_refuse(trade, client, 10.0, close_side="SELL")
        client.close_position.assert_called_once()

    def test_a_venue_that_nets_is_closed_the_ordinary_way(self):
        from bot_program.engine.venue_close import close_or_refuse
        trade = _trade(self.cfg, metadata={})
        client = mock.MagicMock(spec=["market_order"])
        client.market_order.return_value = {"status": "FILLED"}
        close_or_refuse(trade, client, 10.0, close_side="SELL",
                        client_order_id="EXIT-2")
        client.market_order.assert_called_once()
        self.assertEqual(client.market_order.call_args.args[1], "SELL")

    def test_the_kill_switch_closes_by_position_id_too(self):
        """The worst place in the platform to send the opposite trade: the
        switch fires because something is already wrong, and its flatten
        would have doubled the exposure it was pressed to remove."""
        from bot_program.engine.kill_switch import _close_asset_trade
        trade = _trade(self.cfg, metadata={"broker_position_id": "P88",
                                           "initial_stop_loss": 98.0})
        client = self._etoro_like()
        client.close_position.return_value = {"status": "FILLED",
                                              "avgPrice": "97",
                                              "executedQty": "10"}
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            _close_asset_trade(trade, timezone.now())
        client.close_position.assert_called_once()
        client.market_order.assert_not_called()

    def test_the_retry_drain_closes_by_position_id_too(self):
        from bot_program.pending_closes import retry_trade_close
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"broker_position_id": "P99",
                                 "initial_stop_loss": 98.0})
        client = self._etoro_like()
        client.close_position.return_value = {"status": "FILLED",
                                              "avgPrice": "97",
                                              "executedQty": "10"}
        client.get_positions = mock.MagicMock(
            return_value=[{"symbol": "AAPL", "qty": "10", "side": "BUY"}])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            retry_trade_close(trade)
        client.close_position.assert_called_once()
        client.market_order.assert_not_called()


# ── the close is proven by the open order, never by a fresh list ──────────

class TheCloseIsProvenByTheOpenOrderTests(TestCase):
    """MEASURED 2026-09-23 on eToro's demo segment: the close order is
    findable nowhere, the OPEN order's positionExecutions[0].state turns
    "closed" ~8 s later behind transient 500s, and /portfolio lags ~60 s
    both ways. Every path that books a close reads the venue's own word
    first and never a fresh position list inside the lag."""

    ROUTER = "bot_program.engine.broker_router.client_for_symbol"

    def setUp(self):
        self.user = _user("proof_u")
        self.cfg = _cfg(self.user)

    def _venue(self, state="closed", book=None, lag=60):
        from tests.test_venue_drift import EtoroTrader as _DriftEtoro
        venue = _DriftEtoro(book or [])
        venue.PORTFOLIO_LAG_S = lag
        venue.close_needs_position_id = lambda: True
        venue.proofs = []
        venue.closes = []

        def position_state(order_id, **kw):
            venue.proofs.append((order_id, kw))
            return state

        def close_position(position_id, symbol, units=None, *,
                           open_order_id=""):
            venue.closes.append((position_id, symbol, units, open_order_id))
            return {"orderId": "383413813", "positionId": position_id,
                    "status": "PENDING", "executedQty": "0.0",
                    "openOrderId": open_order_id, "positionState": None}

        def market_order(*_a, **_k):
            # the real adapter HAS market_order (it opens; a SELL is
            # sellShort) — the kill switch reads its presence and then
            # closes through close_or_refuse; a client without one is
            # "nothing submitted" and books at the mark. It must never
            # be called on a close.
            raise AssertionError("market_order must not be called on "
                                 "an eToro close")

        venue.market_order = market_order
        venue.position_state = position_state
        venue.close_position = close_position
        return venue

    def _row(self, age_s=600, broker="etoro", **kw):
        from bot_program.models import AssetBotTrade
        meta = {"initial_stop_loss": 98.0, "broker": broker,
                "broker_position_id": "3603281458"}
        meta.update(kw.pop("metadata", {}))
        trade = _trade(self.cfg, broker_order_id="383454450", metadata=meta,
                       **kw)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timezone.timedelta(seconds=age_s))
        trade.refresh_from_db()
        return trade

    def _working(self, broker="etoro"):
        return self._row(status="CLOSE_PENDING", broker=broker, metadata={
            "close_order_working": True,
            "close_working_order_id": "383413813",
            "close_sent_at": timezone.now().isoformat()})

    def _held(self):
        return [{"symbol": "AAPL", "qty": "10", "side": "BUY"}]

    def test_close_or_refuse_hands_the_open_order_id_to_the_adapter(self):
        from bot_program.engine.venue_close import close_or_refuse
        trade = self._row()
        venue = self._venue()
        close_or_refuse(trade, venue, 10.0, close_side="SELL",
                        client_order_id="EXIT-1")
        self.assertEqual(venue.closes,
                         [("3603281458", "AAPL", 10.0, "383454450")])
        client = mock.MagicMock(spec=["market_order", "close_position",
                                      "close_needs_position_id", "ticker"])
        client.close_needs_position_id.return_value = True
        client.close_position.return_value = {"orderId": "c1",
                                              "status": "PENDING"}
        close_or_refuse(trade, client, 10.0, close_side="SELL",
                        client_order_id="EXIT-1")
        self.assertEqual(client.close_position.call_args.kwargs, {})

    def test_a_close_the_venue_has_not_proven_lands_close_pending_not_closed(self):
        from bot_program.asset_engine.stock_bot import StockBot
        trade = self._row()
        venue = self._venue(state=None)
        with self.assertLogs("bot_program.asset_engine.base", level="ERROR"):
            closed = StockBot(self.cfg)._close_trade(trade, Decimal("98"),
                                                     venue, reason="TIME")
        self.assertFalse(closed)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertTrue(trade.metadata.get("close_order_working"))
        self.assertEqual(trade.metadata.get("close_working_order_id"),
                         "383413813")
        self.assertTrue(trade.metadata.get("close_sent_at"))
        self.assertEqual(len(venue.closes), 1)

    def test_the_drain_finalises_on_the_proof_not_on_a_fresh_portfolio_read(self):
        from bot_program.pending_closes import retry_trade_close
        trade = self._working()
        venue = self._venue(state="closed", book=self._held())  # stale list
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertTrue(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("RETRY_VENUE_PROVED_CLOSED", trade.reason or "")
        self.assertEqual(trade.metadata.get("exit_fill_source"), "mark")
        self.assertEqual(venue.proofs,
                         [("383454450", {"attempts": 1, "delay": 0.0})])
        self.assertEqual(venue.closes, [])

    def test_a_queued_close_the_venue_still_shows_open_blocks_and_never_resends(self):
        from bot_program.pending_closes import retry_trade_close
        trade = self._working()
        venue = self._venue(state="open", book=self._held())
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIn("queued", trade.metadata.get("close_blocked_why", ""))
        self.assertFalse(trade.metadata.get("close_retry_attempts"))
        self.assertEqual(venue.closes, [])

    def test_a_stale_portfolio_hit_inside_the_lag_spends_no_attempt(self):
        from bot_program.pending_closes import retry_trade_close
        trade = self._working()
        venue = self._venue(state=None, book=self._held())
        with mock.patch(self.ROUTER, return_value=venue), \
                self.assertLogs("bot_program.pending_closes", level="WARNING"):
            self.assertFalse(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertFalse(trade.metadata.get("close_retry_attempts"))
        self.assertEqual(venue.closes, [])

    def test_a_fresh_portfolio_miss_inside_the_lag_is_not_flat(self):
        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import retry_trade_close
        trade = self._row(status="CLOSE_PENDING", age_s=2)
        venue = self._venue(state=None, book=[])
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(venue.closes, [])
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timezone.timedelta(seconds=120))
        trade.refresh_from_db()
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertTrue(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("RETRY_ALREADY_FLAT", trade.reason or "")

    def test_the_kill_switch_leaves_an_unproven_etoro_close_pending(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        trade = self._row()
        venue = self._venue(state=None, book=self._held())
        with mock.patch(self.ROUTER, return_value=venue), \
                self.assertRaises(RuntimeError):
            _close_asset_trade(trade, timezone.now())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertTrue(trade.metadata.get("close_order_working"))
        self.assertEqual(trade.metadata.get("close_working_order_id"),
                         "383413813")
        self.assertTrue(trade.metadata.get("close_sent_at"))
        self.assertIsNone(trade.exit_price)
        self.assertEqual(len(venue.closes), 1)
        self.assertEqual(venue.closes[0][3], "383454450")

    def test_the_kill_switch_inside_the_lag_sends_the_close_instead_of_booking_flat(self):
        """Pressed within seconds of the entry fill, the switch reads an
        eToro list that does not show the position yet. Before D3 the
        cancel-window reviser read that as 'all filled', found nothing
        left to send and booked CLOSED over a position the venue held.
        Inside the lag the reviser stands down: the close is SENT, stays
        unproven, and the row lands CLOSE_PENDING."""
        from bot_program.engine.kill_switch import _close_asset_trade
        trade = self._row(age_s=2)
        venue = self._venue(state=None, book=[])
        with mock.patch(self.ROUTER, return_value=venue), \
                self.assertRaises(RuntimeError):
            _close_asset_trade(trade, timezone.now())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertIsNone(trade.exit_price)
        self.assertEqual(len(venue.closes), 1)

    def test_the_kill_switch_never_resends_over_a_queued_etoro_close(self):
        """kill_switch: a queued eToro close has no cancel_order, so the
        switch refuses — nothing sent, never a second close."""
        from bot_program.engine.kill_switch import _close_asset_trade
        trade = self._working()
        venue = self._venue(state="open", book=self._held())
        with mock.patch(self.ROUTER, return_value=venue), \
                self.assertRaises(RuntimeError) as cm:
            _close_asset_trade(trade, timezone.now())
        self.assertIn("cancel", str(cm.exception).lower())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(venue.closes, [])
        self.assertTrue(trade.metadata.get("close_order_working"))

    def test_a_venue_that_says_open_is_never_finalised_on_a_flat_list(self):
        from bot_program.pending_closes import retry_trade_close
        trade = self._row(status="CLOSE_PENDING", age_s=600)
        venue = self._venue(state="open", book=[])
        with mock.patch(self.ROUTER, return_value=venue), \
                self.assertLogs("bot_program.pending_closes", level="WARNING"):
            self.assertFalse(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(venue.closes, [])
        self.assertNotIn("RETRY_ALREADY_FLAT", trade.reason or "")
        self.assertFalse(trade.metadata.get("close_retry_attempts"))

    def test_the_proof_is_not_asked_of_a_venue_that_did_not_carry_the_row(self):
        from bot_program.pending_closes import retry_trade_close
        trade = self._working(broker="ibkr")
        venue = self._venue(state="closed", book=[])
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(retry_trade_close(trade))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(venue.proofs, [])
        self.assertEqual(venue.closes, [])


# ── a refused cancel, proved one way or the other ───────────────────────

class ARefusedCancelIsProvedNotGuessedTests(TestCase):
    """Under FifoEndOfDay the bracket legs ride the position and Saxo cancels
    them WITH it, so the DELETE the close path sends next is refused for an
    order that is already gone. Answering False there stamped the row and
    logged CRITICAL on essentially every healthy close, and the one signal
    that means "a full-size GTC exit is loose at the broker" became routine."""

    def _trader(self, extra_routes):
        from tests.test_saxo_client import (ACCOUNTS_ME, CLIENT_ME, _Acct,
                                            _FakeSession)
        from bot_program.engine.saxo_client import SaxoTrader
        sess = _FakeSession(routes=[CLIENT_ME, ACCOUNTS_ME] + extra_routes)
        return SaxoTrader(_Acct(), token="t", session=sess), sess

    REFUSED = ("DELETE", "trade/v2/orders", 404,
               {"ErrorCode": "OrderNotFound", "Message": "no such order"})

    def test_refused_and_gone_from_the_working_list_is_a_moot_cancel(self):
        t, _ = self._trader([self.REFUSED,
                             ("GET", "port/v1/orders", 200, {"Data": []})])
        with self.assertLogs("bot_program.engine.saxo_client", level="INFO"):
            self.assertIs(t.cancel_order("55"), True)

    def test_refused_while_still_working_is_a_refusal(self):
        t, _ = self._trader([self.REFUSED,
                             ("GET", "port/v1/orders", 200,
                              {"Data": [{"OrderId": "55"}]})])
        with self.assertLogs("bot_program.engine.saxo_client", level="ERROR"):
            self.assertIs(t.cancel_order("55"), False)

    def test_refused_with_an_unreadable_working_list_is_a_refusal(self):
        """"Could not ask" is not proof, and this bool exists so that a leg
        still resting can never read as cancelled."""
        t, _ = self._trader([self.REFUSED,
                             ("GET", "port/v1/orders", 500, {})])
        with self.assertLogs("bot_program.engine.saxo_client", level="ERROR"):
            self.assertIs(t.cancel_order("55"), False)

    def test_a_refused_session_proves_nothing_and_reads_nothing(self):
        """A 401 says the request never reached the order book, so there is
        nothing to prove — and no point spending a read to look."""
        t, sess = self._trader([("DELETE", "trade/v2/orders", 401, {}),
                                ("GET", "port/v1/orders", 200, {"Data": []})])
        with self.assertLogs("bot_program.engine.saxo_client", level="ERROR"):
            self.assertIs(t.cancel_order("55"), False)
        self.assertFalse(any("port/v1/orders" in u for _m, u, _k in sess.calls))

    def test_a_clean_cancel_needs_no_proof(self):
        t, sess = self._trader([("DELETE", "trade/v2/orders", 200, {})])
        self.assertIs(t.cancel_order("55"), True)
        self.assertFalse(any("port/v1/orders" in u for _m, u, _k in sess.calls))

    def test_an_unreadable_audit_log_is_unknown_and_never_dead(self):
        """order_status computes `dead` as the else-branch of two absences,
        and _await_fill swallows a refused read into rows=[] — so without the
        unreadable flag a 429 on the audit log manufactured `dead`, and base.py
        cancels a row on `dead`."""
        t, _ = self._trader([("GET", "port/v1/orders/CK==/55", 404, {}),
                             ("GET", "cs/v1/audit/orderactivities", 429,
                              {"ErrorCode": "RateLimited"})])
        self.assertEqual(t.order_status("55")["state"], "unknown")


class ALooseProtectiveLegReachesAHumanTests(TestCase):
    """The flag was written at six places in base.py and read by no view,
    template, alert or task — while the identical event on the entry path
    pages a human. A resting exit against a flat book OPENS a position when it
    fires, and no row here describes it."""

    def setUp(self):
        self.user = _user("loose_u")
        self.cfg = _cfg(self.user, name="LOOSE")

    def _closing(self):
        client = _client({"status": "FILLED", "avgPrice": "97",
                          "executedQty": "10"}, last="98")
        client.cancel_order = mock.MagicMock(return_value=False)
        return client

    def _row(self):
        return _trade(self.cfg, metadata={"initial_stop_loss": 98.0,
                                          "protective_order_ids": ["S1", "T1"],
                                          "protected": True})

    def test_the_operator_is_paged_and_the_row_names_the_legs(self):
        from bot_program.asset_engine.stock_bot import StockBot
        trade = self._row()
        with mock.patch("bot_program.notifications.notify_staff") as paged:
            with self.assertLogs("bot_program.asset_engine.base",
                                 level="CRITICAL"):
                StockBot(self.cfg)._close_trade(trade, Decimal("98"),
                                                self._closing(), reason="SL")
        paged.assert_called_once()
        self.assertIn("still rest", paged.call_args.kwargs["title"])
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["protective_legs_unconfirmed_ids"],
                         ["S1", "T1"])
        self.assertIn("protective_legs_unconfirmed_at", trade.metadata)
        # The exit really happened, so the row is CLOSED and the alert is the
        # only thing left to do.
        self.assertEqual(trade.status, "CLOSED")

    def test_an_alert_that_fails_does_not_turn_the_close_into_pending(self):
        """It runs inside _close_trade's try, whose handler marks the row
        CLOSE_PENDING — so a raising alert would turn a completed close into a
        pending one: the failure mode of the warning about the failure."""
        from bot_program.asset_engine.stock_bot import StockBot
        trade = self._row()
        with mock.patch("bot_program.notifications.notify_staff",
                        side_effect=RuntimeError("no channel")):
            with self.assertLogs("bot_program.asset_engine.base",
                                 level="CRITICAL"):
                StockBot(self.cfg)._close_trade(trade, Decimal("98"),
                                                self._closing(), reason="SL")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")


# ── every handle, and a row that says when none of them works ───────────

class TheStopMoveTriesEveryHandleTests(TestCase):
    """On Saxo protective_trade_id is the PositionId, which resolves the legs
    under FifoEndOfDay and resolves NOTHING under the real-time netting
    profiles — where the row's own protective_stop_id is what would work. So
    stopping at the first handle meant break-even and trailing never moved a
    broker-held stop again on those accounts, for the life of every position,
    with nothing on the row saying so."""

    def setUp(self):
        self.user = _user("walk_u")
        self.cfg = _cfg(self.user, name="WALK")
        self.cfg.extras = {**(self.cfg.extras or {}), "breakeven_at_r": 0.5}
        self.cfg.save(update_fields=["extras"])

    def _row(self, **meta):
        return _trade(self.cfg, metadata={"initial_stop_loss": 98.0,
                                          "protected": True, **meta})

    def _mover(self, ok_for=()):
        """A client whose stop mover accepts only the ids in `ok_for`."""
        client = mock.MagicMock(spec=["modify_protective", "ticker"])
        client.ticker.return_value = {"lastPrice": "104"}

        def move(oid, price):
            if str(oid) in {str(x) for x in ok_for}:
                return {"ok": True, "price": price}
            return {"ok": False, "reason": f"leg {oid} is not a stop"}

        client.modify_protective.side_effect = move
        return client

    def _manage(self, trade, client):
        from bot_program.asset_engine.stock_bot import StockBot
        bot = StockBot(self.cfg)
        # (trade, price, client) — the price comes second.
        return bot._manage_broker_stop(trade, Decimal("104"), client)

    def test_the_named_leg_is_tried_after_the_position_handle(self):
        trade = self._row(protective_trade_id="P1", protective_stop_id="S1")
        client = self._mover(ok_for=["S1"])
        self._manage(trade, client)
        asked = [c.args[0] for c in client.modify_protective.call_args_list]
        self.assertEqual(asked[:2], ["P1", "S1"])

    def test_the_flat_list_is_tried_last_of_all(self):
        trade = self._row(protective_trade_id="P1", protective_stop_id="S1",
                          protective_order_ids=["X9"])
        client = self._mover(ok_for=["X9"])
        self._manage(trade, client)
        asked = [c.args[0] for c in client.modify_protective.call_args_list]
        self.assertEqual(asked, ["P1", "S1", "X9"])

    def test_the_same_id_under_two_keys_is_asked_once(self):
        trade = self._row(protective_trade_id="P1", protective_stop_id="P1",
                          protective_order_ids=["P1"])
        client = self._mover(ok_for=[])
        self._manage(trade, client)
        self.assertEqual(client.modify_protective.call_count, 1)

    def test_a_single_id_stored_as_a_string_is_not_split_into_characters(self):
        trade = self._row(protective_order_ids="77")
        client = self._mover(ok_for=["77"])
        self._manage(trade, client)
        asked = [c.args[0] for c in client.modify_protective.call_args_list]
        self.assertEqual(asked, ["77"])

    def test_the_walk_is_bounded_in_wall_clock(self):
        """Three handles must not be able to triple a transport outage for
        every position queued behind this one."""
        from bot_program.asset_engine.stock_bot import StockBot
        trade = self._row(protective_trade_id="P1", protective_stop_id="S1",
                          protective_order_ids=["X9"])
        client = self._mover(ok_for=["X9"])
        with mock.patch.object(StockBot, "STOP_MOVE_WALK_BUDGET_S", 0.0):
            self._manage(trade, client)
        asked = [c.args[0] for c in client.modify_protective.call_args_list]
        self.assertEqual(asked, ["P1"], "the first handle is always asked")
        trade.refresh_from_db()
        self.assertIn("within the walk budget",
                      trade.metadata["stop_move_last_error"])

    def test_a_refusal_is_counted_and_carries_the_venues_own_words(self):
        trade = self._row(protective_trade_id="P1")
        client = self._mover(ok_for=[])
        self._manage(trade, client)
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["stop_move_failures"], 1)
        self.assertIn("is not a stop", trade.metadata["stop_move_last_error"])
        self.assertNotIn("stop_rules_inert", trade.metadata)

    def test_three_refusals_stamp_the_row_inert_with_its_reason(self):
        """One failure is a blip — an expired session, a 202 the venue never
        confirmed. Three consecutive attempts are a fact about the ROW."""
        from bot_program.asset_engine.stock_bot import StockBot
        trade = self._row(protective_trade_id="P1")
        client = self._mover(ok_for=[])
        for _ in range(StockBot.STOP_MOVE_FAILURES_BEFORE_INERT):
            self._manage(trade, client)
            trade.refresh_from_db()
        self.assertEqual(trade.metadata["stop_rules_inert"], "legs_unmovable")
        self.assertIn("is not a stop",
                      trade.metadata["stop_rules_inert_detail"])

    def test_a_leg_that_moves_clears_the_whole_record_of_failure(self):
        """Leaving the count would make the next single failure look like the
        fourth and stamp the row on a blip."""
        trade = self._row(protective_trade_id="P1", protective_stop_id="S1")
        self._manage(trade, self._mover(ok_for=[]))
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["stop_move_failures"], 1)
        self._manage(trade, self._mover(ok_for=["S1"]))
        trade.refresh_from_db()
        self.assertNotIn("stop_move_failures", trade.metadata)
        self.assertNotIn("stop_rules_inert", trade.metadata)

    def test_the_operator_lane_walks_the_same_handles(self):
        """A row the bot's rules can move and the operator's dialog cannot is
        a row whose behaviour depends on which lane touched it."""
        from bot_program.adjust_levels import _move_broker_leg
        trade = self._row(protective_trade_id="P1", protective_stop_id="S1")
        client = self._mover(ok_for=["S1"])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            ok, _note = _move_broker_leg(self.user, trade, Decimal("104"),
                                         leg="stop")
        self.assertTrue(ok)
        asked = [c.args[0] for c in client.modify_protective.call_args_list]
        self.assertEqual(asked, ["P1", "S1"])

    def test_the_operator_is_told_what_every_handle_said(self):
        from bot_program.adjust_levels import _move_broker_leg
        trade = self._row(protective_trade_id="P1", protective_stop_id="S1")
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=self._mover(ok_for=[])):
            ok, note = _move_broker_leg(self.user, trade, Decimal("104"),
                                        leg="stop")
        self.assertFalse(ok)
        self.assertIn("P1:", note)
        self.assertIn("S1:", note)


# ── a delayed print, recorded as one ────────────────────────────────────

class ADelayedMarkSaysSoTests(TestCase):
    """SaxoTrader returns the delay beside every price and the platform read
    neither field, so a 15-minute-old print became the recorded exit price with
    nothing saying it was an estimate. On SIM that delay is the NORMAL state of
    every CFD: FX is real-time, everything else is delayed or NoAccess unless
    the demo account is linked to a funded live one."""

    def setUp(self):
        self.user = _user("delay_u")
        self.cfg = _cfg(self.user, name="DELAY")

    def test_the_three_states_of_a_tick(self):
        from bot_program.pending_closes import mark_quality
        self.assertEqual(mark_quality({"lastPrice": "1", "delayed_minutes": 15}),
                         {"mark_delayed_minutes": 15})
        self.assertEqual(mark_quality({"lastPrice": "1", "delayed": True}),
                         {"mark_delayed": True})
        # The venue SAID zero: a real-time print, and nothing to record.
        self.assertEqual(mark_quality({"lastPrice": "1", "delayed_minutes": 0}),
                         {})
        # The feed never mentioned delay, which is not the same as real-time —
        # and still nothing to claim.
        self.assertEqual(mark_quality({"lastPrice": "1"}), {})
        self.assertEqual(mark_quality(None), {})

    def test_an_exit_booked_from_a_delayed_mark_records_the_delay(self):
        from bot_program.pending_closes import resolve_exit_fill
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        fill = resolve_exit_fill(trade, None, mark=Decimal("97"),
                                 mark_info={"mark_delayed_minutes": 15})
        self.assertEqual(fill["source"], "mark")
        self.assertEqual(fill["metadata"]["mark_delayed_minutes"], 15)

    def test_an_exit_booked_from_the_brokers_own_fill_carries_no_delay(self):
        """A row whose exit came from the fill must not carry a delay that
        belonged to a mark nobody used."""
        from bot_program.pending_closes import resolve_exit_fill
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        fill = resolve_exit_fill(trade, {"status": "FILLED", "avgPrice": "96",
                                         "executedQty": "10"},
                                 mark=Decimal("97"),
                                 mark_info={"mark_delayed_minutes": 15})
        self.assertEqual(fill["source"], "broker")
        self.assertIsNone(fill["metadata"]["mark_delayed_minutes"])

    def test_the_reader_carries_the_delay_off_the_tick(self):
        from bot_program.pending_closes import mark_with_quality
        trade = _trade(self.cfg, metadata={"initial_stop_loss": 98.0})
        client = mock.MagicMock(spec=["ticker"])
        client.ticker.return_value = {"lastPrice": "97.5",
                                      "delayed_minutes": 15}
        mark, quality = mark_with_quality(trade, client)
        self.assertEqual(mark, Decimal("97.5"))
        self.assertEqual(quality, {"mark_delayed_minutes": 15})

    def test_an_unpriced_tick_still_reports_what_it_knew(self):
        """lastPrice 0 is Saxo's NoAccess answer, and the delay it reported
        beside it is still a fact about the feed."""
        from bot_program.pending_closes import mark_with_quality
        trade = _trade(self.cfg, metadata={"initial_stop_loss": 98.0})
        client = mock.MagicMock(spec=["ticker"])
        client.ticker.return_value = {"lastPrice": "0", "delayed_minutes": 20}
        mark, quality = mark_with_quality(trade, client)
        self.assertIsNone(mark)
        self.assertEqual(quality, {"mark_delayed_minutes": 20})

    def test_a_ticker_that_raises_is_no_mark_and_no_claim(self):
        from bot_program.pending_closes import mark_with_quality
        trade = _trade(self.cfg, metadata={"initial_stop_loss": 98.0})
        client = mock.MagicMock(spec=["ticker"])
        client.ticker.side_effect = RuntimeError("no session")
        self.assertEqual(mark_with_quality(trade, client), (None, {}))

    def test_the_flat_finalise_records_the_delay_it_booked(self):
        """This is the path the finding names: the broker is already flat,
        there is no fill to read, and the mark IS the exit price."""
        from bot_program.pending_closes import retry_trade_close
        trade = _trade(self.cfg, status="CLOSE_PENDING",
                       metadata={"initial_stop_loss": 98.0})
        client = _client({"status": "FILLED"}, last="97")
        client.ticker = mock.MagicMock(return_value={"lastPrice": "97",
                                                     "delayed_minutes": 15})
        client.get_positions = mock.MagicMock(return_value=[])
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            retry_trade_close(trade)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.metadata["mark_delayed_minutes"], 15)
