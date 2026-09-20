"""From "the order is sent" to "the row is right", at the eight seams the
Monday-evening trace broke.

Every one of these needs an order to EXIST before it bites, which is why
none of them could be found by reading the adapter against its
documentation — they are about what the platform does with the answer.

  * an order that came back PENDING could never be resolved, because
    SaxoTrader had no order_status and PENDING is the DEFAULT outcome of a
    slow audit log. The row was terminal: unalerted, unreconciled (the
    sweep skips entry_working rows by design), its symbol blocked forever
    and its concurrency slot held.
  * a refused stop leg was still reported as protection, which switches
    bot-side SL/TP off — a position with no stop anywhere, unmanaged.
  * a partial fill at placement was booked as a finished position, leaving
    the remainder live with no owner and both legs sized for the whole
    order, so the stop would close what printed and OPEN the rest.
  * the close ran on a 20-second client timeout with no in-doubt guard,
    while the entry deliberately waits 75 s — past Saxo's own sixty-second
    broker deadline — and an exception from the close is read as a refusal,
    which cancels the brackets and re-sends: a closed long becomes a
    full-size short.
  * the close called _raise_for before reading the body, so an order that
    EXISTS was reported as refused — the bug market_order carries a
    paragraph about, in the one place whose body has the same multi-order
    shape that answers 400 WITH an OrderId.
  * X-Request-ID was a fresh uuid4 on every write, which DISABLES Saxo's
    only duplicate guard — while three call sites in this platform say in
    their comments that the broker refuses the second copy.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program.engine import saxo_client as sc
from bot_program.engine.saxo_client import (SaxoApiError, SaxoOrderInDoubt,
                                            SaxoTrader)
from tests.test_saxo_client import (ACCOUNTS_ME, CLIENT_ME, DETAILS_EURUSD,
                                    FILLED, SEARCH_EURUSD, _Acct, _FakeSession,
                                    _fx, trader)

PLACED = ("POST", "trade/v2/orders", 200, {"OrderId": "1000001"})
ORDER_ROW = ("GET", "port/v1/orders/CK==/1000001", 200, {"Data": [
    {"OrderId": "1000001", "OpenOrderType": "Market", "Amount": 5000}]})
NO_ORDER_ROW = ("GET", "port/v1/orders/CK==/1000001", 200, {"Data": []})
NOTHING_YET = ("GET", "cs/v1/audit/orderactivities?OrderId=1000001", 200,
               {"Data": [{"OrderId": "1000001", "Status": "Placed"}]})
CANCELLED = ("GET", "cs/v1/audit/orderactivities?OrderId=1000001", 200,
             {"Data": [{"OrderId": "1000001", "Status": "Cancelled"}]})
PARTIAL = ("GET", "cs/v1/audit/orderactivities?OrderId=1000001", 200, {"Data": [
    {"OrderId": "1000001", "Status": "Fill", "FillAmount": 2000,
     "FilledAmount": 2000, "AveragePrice": 1.1002, "PositionId": "P1"}]})


class OrderStatusTests(SimpleTestCase):
    """base.py's WORKING path exists and works; it just had nothing to ask."""

    def setUp(self):
        sc._UIC_CACHE.clear()

    def test_a_fill_in_the_audit_log_is_filled(self):
        t, _ = trader([ORDER_ROW, FILLED])
        st = t.order_status("1000001")
        self.assertEqual(st["state"], "filled")
        self.assertEqual(st["filled"], 5000.0)
        self.assertEqual(st["avgPrice"], 1.1001)

    def test_still_in_the_order_list_is_working(self):
        t, _ = trader([ORDER_ROW, NOTHING_YET])
        self.assertEqual(t.order_status("1000001")["state"], "working")

    def test_gone_from_the_list_with_no_fill_is_dead(self):
        """Saxo answered BOTH questions, so this is not an unknown — and the
        difference decides whether base.py cancels the row or waits forever."""
        t, _ = trader([NO_ORDER_ROW, NOTHING_YET])
        self.assertEqual(t.order_status("1000001")["state"], "dead")

    def test_a_404_from_the_order_list_is_an_answer(self):
        t, _ = trader([("GET", "port/v1/orders/CK==/1000001", 404,
                        {"ErrorCode": "OrderNotFound"}), NOTHING_YET])
        self.assertEqual(t.order_status("1000001")["state"], "dead")

    def test_a_cancelled_order_is_dead(self):
        t, _ = trader([NO_ORDER_ROW, CANCELLED])
        st = t.order_status("1000001")
        self.assertEqual(st["state"], "dead")
        self.assertEqual(st["status"], "CANCELLED")

    def test_a_partial_no_longer_working_counts_what_printed(self):
        t, _ = trader([NO_ORDER_ROW, PARTIAL])
        st = t.order_status("1000001")
        self.assertEqual(st["state"], "filled")
        self.assertEqual(st["filled"], 2000.0)

    def test_a_read_that_fails_is_unknown_and_never_dead(self):
        """"Could not ask" is not an answer: base.py waits on unknown and
        CANCELS the row on dead."""
        t, _ = trader([("GET", "port/v1/orders/CK==/1000001", 500, {}),
                       ("GET", "cs/v1/audit/orderactivities", 500, {})])
        self.assertEqual(t.order_status("1000001")["state"], "unknown")

    def test_no_order_id_is_unknown(self):
        t, _ = trader([])
        self.assertEqual(t.order_status("")["state"], "unknown")

    def test_the_working_order_list_is_readable(self):
        t, _ = trader([("GET", "port/v1/orders", 200, {"Data": [
            {"OrderId": "77"}, {"OrderId": "78"}, {"NoId": 1}]})])
        self.assertEqual(t.resting_order_ids(), ["77", "78"])

    def test_an_unreadable_order_list_is_none_and_never_empty(self):
        """base._broker_snapshot treats [] as an ANSWER, and
        _protection_vanished then reads "no stop is resting" and un-protects
        a live position on the strength of a read that failed. None is the
        only honest answer to a 500."""
        t, _ = trader([("GET", "port/v1/orders", 500, {})])
        self.assertIsNone(t.resting_order_ids())

    def test_an_account_with_nothing_resting_is_empty_and_not_none(self):
        """The other half: [] has to keep meaning what it says, or the net
        can never fire at all."""
        t, _ = trader([("GET", "port/v1/orders", 200, {"Data": []})])
        self.assertEqual(t.resting_order_ids(), [])


class ARefusedLegIsNotProtectionTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()

    def _place(self, placed_payload, activities):
        t, sess = _fx([("POST", "trade/v2/orders", 200, placed_payload),
                       activities,
                       ("DELETE", "trade/v2/orders", 200, {})])
        out = t.market_order("EURUSD", "BUY", 5000, stop_loss=1.09,
                             take_profit=1.12)
        return out, sess

    def test_a_refused_stop_withdraws_the_accepted_target(self):
        out, sess = self._place(
            {"OrderId": "1000001", "Orders": [
                {"ErrorInfo": {"ErrorCode": "PriceNotInTickSizeIncrements"}},
                {"OrderId": "2000002"}]},
            FILLED)
        self.assertNotIn("protectiveStopId", out)
        self.assertNotIn("protectiveTradeId", out)
        self.assertFalse(out.get("protectedOnFill"))
        self.assertEqual(out.get("protectiveOrders", []), [],
                         "a confirmed cancel leaves nothing resting")
        self.assertTrue(any("DELETE" == m for m, _u, _k in sess.calls),
                        "the accepted sibling is withdrawn")
        self.assertIn("bracket withdrawn", out["protectionNote"])

    def test_a_leg_that_cannot_be_cancelled_is_still_reported(self):
        """It is resting whether we like it or not, and the engine must be
        able to cancel it at the close — but it is still not protection."""
        t, sess = _fx([("POST", "trade/v2/orders", 200,
                        {"OrderId": "1000001", "Orders": [
                            {"ErrorInfo": {"ErrorCode": "Rejected"}},
                            {"OrderId": "2000002"}]}),
                       FILLED,
                       ("DELETE", "trade/v2/orders", 400,
                        {"ErrorCode": "OrderNotFound"})])
        out = t.market_order("EURUSD", "BUY", 5000, stop_loss=1.09,
                             take_profit=1.12)
        self.assertEqual(out.get("protectiveOrders"), ["2000002"])
        self.assertFalse(out.get("protectedOnFill"))
        self.assertNotIn("protectiveStopId", out)
        self.assertIn("NOT confirmed cancelled", out["protectionNote"])

    def test_a_clean_bracket_still_reports_its_protection(self):
        out, _ = self._place(
            {"OrderId": "1000001", "Orders": [{"OrderId": "2000002"},
                                              {"OrderId": "2000003"}]},
            FILLED)
        self.assertEqual(out["protectiveOrders"], ["2000002", "2000003"])
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual(out["protectiveStopId"], "2000002")
        self.assertEqual(out["protectiveTargetId"], "2000003")


class APartialAtPlacementIsStillWorkingTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()

    def test_a_partial_hands_the_row_to_the_poll(self):
        t, _ = _fx([PLACED, PARTIAL])
        out = t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(out["status"], "PARTIALLY_FILLED")
        self.assertTrue(out["working"],
                        "the remainder may be live: only the poll withdraws it")
        self.assertIn("partial at placement", out["protectionNote"])

    def test_a_full_fill_is_not_working(self):
        t, _ = _fx([PLACED, FILLED])
        out = t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(out["status"], "FILLED")
        self.assertNotIn("working", out)


class TheCloseObeysTheEntrysRulesTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()

    POSITION = ("GET", "port/v1/positions/P9", 200, {
        "PositionBase": {"Amount": 5000, "Uic": 21, "AssetType": "FxSpot"}})

    def _closer(self, post):
        return trader([self.POSITION, post,
                       ("GET", "cs/v1/audit/orderactivities?OrderId=1000001",
                        200, {"Data": [
                            {"OrderId": "1000001", "Status": "FinalFill",
                             "FilledAmount": 5000, "AveragePrice": 1.1005}]})])

    def test_a_400_carrying_an_order_id_is_not_a_refusal(self):
        """The close body under FifoEndOfDay is a multi-order body, which is
        exactly the shape Saxo answers 400-with-OrderId for. Raising there
        made the engine cancel the brackets and send a SECOND close."""
        t, _ = self._closer(("POST", "trade/v2/orders", 400, {
            "OrderId": "1000001",
            "Orders": [{"ErrorInfo": {"ErrorCode": "SomethingSecondary"}}]}))
        out = t.close_position("P9", "EURUSD", 5000)
        self.assertEqual(out["orderId"], "1000001")
        self.assertEqual(out["status"], "FILLED")

    def test_a_400_with_no_order_id_is_still_a_refusal(self):
        t, _ = self._closer(("POST", "trade/v2/orders", 400,
                             {"ErrorCode": "OrderNotFound",
                              "Message": "no such position"}))
        with self.assertRaises(SaxoApiError):
            t.close_position("P9", "EURUSD", 5000)

    def test_a_202_is_in_doubt_and_never_a_fill(self):
        t, _ = self._closer(("POST", "trade/v2/orders", 202,
                             {"OrderId": "1000001"}))
        out = t.close_position("P9", "EURUSD", 5000)
        self.assertEqual(out["status"], "UNKNOWN")
        self.assertTrue(out["inDoubt"])
        self.assertEqual(out["executedQty"], "0")

    def test_a_request_that_does_not_come_back_is_in_doubt_not_refused(self):
        import requests

        t, sess = self._closer(PLACED)

        def boom(url, **kw):
            raise requests.ConnectTimeout("nothing came back")

        sess.post = boom
        with self.assertRaises(SaxoOrderInDoubt) as cm:
            t.close_position("P9", "EURUSD", 5000, client_order_id="EXIT-7")
        self.assertTrue(getattr(cm.exception, "in_doubt", False))
        self.assertEqual(cm.exception.reference, "EXIT-7")
        # The reference FIRST: skips.record keeps 200 characters and
        # why_no_trade shows 88, and a timeout string alone is longer.
        self.assertLess(str(cm.exception).index("EXIT-7"), 60)

    def test_the_close_waits_as_long_as_the_entry(self):
        t, sess = self._closer(PLACED)
        t.close_position("P9", "EURUSD", 5000)
        posts = [kw for m, u, kw in sess.calls
                 if m == "POST" and "trade/v2/orders" in u]
        self.assertEqual(posts[0]["timeout"], sc.ORDER_TIMEOUT_S)

    def test_the_close_carries_the_callers_reference(self):
        t, sess = self._closer(PLACED)
        t.close_position("P9", "EURUSD", 5000, client_order_id="EXIT-9")
        body = sess.sent("POST", "trade/v2/orders")
        leg = (body.get("Orders") or [body])[0]
        self.assertEqual(leg.get("ExternalReference"), "EXIT-9")


class TheDuplicateGuardCanFireTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()

    def _placement_header(self, reference):
        t, sess = _fx([PLACED, FILLED])
        t.market_order("EURUSD", "BUY", 5000, client_order_id=reference)
        for m, u, kw in sess.calls:
            if m == "POST" and "trade/v2/orders" in u:
                return kw["headers"]["X-Request-ID"]
        raise AssertionError("no placement was sent")

    def test_the_same_order_carries_the_same_request_id(self):
        """Saxo refuses an identical body inside fifteen seconds ONLY when
        this header repeats — and three call sites in this platform rely on
        the broker refusing the second copy."""
        self.assertEqual(self._placement_header("ENTRY-1"),
                         self._placement_header("ENTRY-1"))

    def test_a_different_order_carries_a_different_one(self):
        self.assertNotEqual(self._placement_header("ENTRY-1"),
                            self._placement_header("ENTRY-2"))

    def test_a_read_or_a_cancel_still_gets_a_fresh_one(self):
        """Two identical cancels must both be allowed to land."""
        t, sess = trader([("DELETE", "trade/v2/orders", 200, {})])
        t.cancel_order("55")
        t.cancel_order("55")
        ids = [kw["headers"]["X-Request-ID"] for m, u, kw in sess.calls
               if m == "DELETE"]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])


# ── the engine's half ───────────────────────────────────────────────────

def _bot(user, asset_class="stock"):
    from bot_program.asset_engine.stock_bot import StockBot
    from bot_program.models import AssetBotConfig
    cfg = AssetBotConfig.objects.create(
        user=user, name="lifecycle", asset_class=asset_class, mode="live",
        enabled=True, symbols=["AAPL"], capital=Decimal("5000"),
        base_currency="EUR")
    return StockBot(cfg), cfg


def _open_trade(cfg, **meta):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("200"), status="OPEN",
        stop_loss=Decimal("190"), take_profit=Decimal("220"),
        paper=False, broker_order_id="1000001", metadata=dict(meta))


class AnOrderThatMayBeLiveStopsTheSymbolTests(TestCase):
    """There is no row to find — that is the whole problem — so the note
    lives on the config. Without it the next tick sends a SECOND order: the
    idempotency key buckets by the minute, so even a broker with a working
    duplicate guard would not see the first one."""

    def setUp(self):
        self.user = User.objects.create_user("idb_u", password="x")
        self.bot, self.cfg = _bot(self.user)

    def test_the_note_is_written_and_read(self):
        self.bot._remember_in_doubt("AAPL", "REF-1")
        self.cfg.refresh_from_db()
        note = self.bot._in_doubt_note("AAPL")
        self.assertIsNotNone(note)
        self.assertEqual(note["reference"], "REF-1")

    def test_propose_entry_refuses_the_symbol_while_it_stands(self):
        from bot_program.asset_engine import skips
        self.bot._remember_in_doubt("AAPL", "REF-1")
        self.assertIsNone(self.bot.propose_entry("AAPL"))
        self.cfg.refresh_from_db()
        self.assertIn(skips.ORDER_IN_DOUBT, str(self.cfg.extras or {}))

    def test_the_note_expires_by_itself(self):
        """A note that never expired would retire the symbol permanently,
        which is the failure this whole file argues against."""
        from datetime import timedelta
        self.bot._remember_in_doubt("AAPL", "REF-1")
        self.cfg.refresh_from_db()
        extras = dict(self.cfg.extras or {})
        old = (timezone.now()
               - timedelta(hours=self.bot.IN_DOUBT_QUIET_HOURS + 1))
        extras["entry_in_doubt"]["AAPL"]["at"] = old.isoformat()
        self.cfg.extras = extras
        self.cfg.save(update_fields=["extras"])
        self.bot.cfg.refresh_from_db()
        self.assertIsNone(self.bot._in_doubt_note("AAPL"))

    def test_another_symbol_is_untouched(self):
        self.bot._remember_in_doubt("AAPL", "REF-1")
        self.assertIsNone(self.bot._in_doubt_note("MSFT"))

    def test_the_entry_path_reads_the_marker_and_not_a_venue_class(self):
        """AST-pinned: the engine must not import one venue's exception, and
        a substring pin would be satisfied by the comment alone."""
        import ast
        import inspect
        import textwrap

        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.execute_entry))
        names = {n.args[1].value for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "getattr"
                 and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)}
        self.assertIn("in_doubt", names)
        self.assertNotIn("SaxoOrderInDoubt", src)


class AnInDoubtCloseIsNeverResentTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("idc_u", password="x")
        self.bot, self.cfg = _bot(self.user)

    def _client(self):
        c = mock.MagicMock(spec=["market_order", "cancel_order", "ticker"])
        c.market_order.side_effect = SaxoOrderInDoubt("EXIT-7", "ReadTimeout")
        c.ticker.return_value = {"lastPrice": "205"}
        return c

    def test_the_row_keeps_its_legs_and_nothing_is_sent_twice(self):
        """The engine read ANY exception from the close as a refusal: it
        cancelled the brackets and re-sent the whole close. Both fill, and a
        closed 10-unit long becomes a 10-unit short with the row CLOSED."""
        trade = _open_trade(self.cfg, protective_order_ids=["S1", "T1"],
                            initial_stop_loss=190.0)
        client = self._client()
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR") as cm:
            out = self.bot._close_trade(trade, Decimal("205"), client,
                                        reason="TIME")
        self.assertFalse(out)
        self.assertEqual(client.market_order.call_count, 1)
        client.cancel_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"],
                         "EXIT-7")
        self.assertTrue(any("MAY be live" in m for m in cm.output))


class ProtectionMeansAStopTests(SimpleTestCase):

    def test_the_flag_is_set_only_where_a_stop_is_named(self):
        """`protected` switches bot-side SL/TP off completely, so stamping it
        on any protective id let a bracket whose STOP was refused claim
        protection it did not have. Read off the source, because the branch
        lives inside execute_entry."""
        import inspect
        import textwrap

        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.execute_entry))
        before = src.split('entry_meta["protected"] = True')[0]
        condition = before.rsplit("if ", 1)[1]
        for handle in ("protectiveStopId", "protectiveTradeId",
                       "protectedOnFill"):
            self.assertIn(handle, condition,
                          "the protected flag must be gated on a real handle")


class AnUnpollableVenueStillWithdrawsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("unp_u", password="x")
        self.bot, self.cfg = _bot(self.user)

    def test_an_old_queued_order_is_withdrawn_even_with_no_order_status(self):
        """It used to log and RETURN — before the withdrawal — so a venue
        that cannot be polled kept its queued rows forever: each holding a
        concurrency slot, blocking its symbol, and skipped by reconciliation
        by design."""
        from datetime import timedelta
        old = (timezone.now()
               - timedelta(hours=self.bot.ENTRY_WORKING_MAX_HOURS + 1))
        trade = _open_trade(self.cfg, entry_working=True,
                            entry_working_since=old.isoformat(),
                            qty_requested=10.0)
        client = mock.MagicMock(spec=["market_order", "cancel_order"])
        with mock.patch("bot_program.asset_engine.base.cancel_working_entry") \
                as withdraw, self.assertLogs(
                    "bot_program.asset_engine.base", level="ERROR"):
            self.bot._poll_working_entry(trade, client)
        withdraw.assert_called_once()
        self.assertIn("cannot report an order", str(withdraw.call_args))

    def test_a_young_one_is_left_alone(self):
        trade = _open_trade(self.cfg, entry_working=True,
                            entry_working_since=timezone.now().isoformat(),
                            qty_requested=10.0)
        client = mock.MagicMock(spec=["market_order"])
        with mock.patch("bot_program.asset_engine.base.cancel_working_entry") \
                as withdraw, self.assertLogs(
                    "bot_program.asset_engine.base", level="ERROR"):
            self.bot._poll_working_entry(trade, client)
        withdraw.assert_not_called()


class AnUnmanagedPositionSaysSoTests(SimpleTestCase):

    def test_the_unpriced_branch_records_and_logs(self):
        """A Saxo SIM quote of 0 (NoAccess, which is every CFD on an unlinked
        demo) skipped the time stop, the vanished-stop net, break-even,
        trailing and bot-side SL/TP — in silence, for the life of the
        position."""
        import inspect
        import textwrap

        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.manage_positions))
        gate = src.split("if price is None or price <= 0:")[1].split(
            "continue")[0]
        self.assertIn("skips.record", gate)
        self.assertIn("NO_PRICE", gate)
        self.assertIn("logger.warning", gate)


class AnUnconfirmedCloseIsNotAClosedRowTests(TestCase):
    """UNKNOWN is not in CLOSE_REFUSED_STATUSES, so a 202 close passed
    through as a success and the row was finalised CLOSED against a position
    that may still be live — the same double exposure the FifoEndOfDay work
    was about, arriving by a different door."""

    def setUp(self):
        self.user = User.objects.create_user("unc_u", password="x")
        self.bot, self.cfg = _bot(self.user)

    def test_a_202_close_leaves_the_row_open_and_marked(self):
        client = mock.MagicMock(spec=["market_order", "cancel_order", "ticker"])
        client.ticker.return_value = {"lastPrice": "205"}
        client.market_order.return_value = {
            "status": "UNKNOWN", "executedQty": "0", "avgPrice": "0",
            "inDoubt": True, "reference": "EXIT-11"}
        trade = _open_trade(self.cfg, protective_order_ids=["S1"],
                            initial_stop_loss=190.0)
        with self.assertLogs("bot_program.asset_engine.base", level="ERROR"):
            out = self.bot._close_trade(trade, Decimal("205"), client,
                                        reason="TIME")
        self.assertFalse(out)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"],
                         "EXIT-11")
        client.cancel_order.assert_not_called()
