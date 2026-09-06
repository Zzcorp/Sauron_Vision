"""An order the broker has not filled is not a position.

`market_order` sampled the parent once, one second after placement. A
market order held outside regular hours, on a halted symbol, or simply not
acked inside that second sits PreSubmitted/Submitted with nothing filled —
and the client returned status PRESUBMITTED, executedQty 0, and
protectedOnFill True because its children rested. Both entry paths booked
that as a FULL-SIZE OPEN row at the pre-order ticker price, marked
protected. Reconciliation then found no position at the broker, closed the
row as an orphan and cancelled its protective legs — leaving the parent to
fill afterwards, naked, into a row the platform had already closed.

The answer is named WORKING. The row exists so the order has an owner (the
duplicate guard sees it, the kill switch can withdraw it) but claims no
position, no price and no protection; the tick polls the broker until it
fills, dies, or outlives its window.

Run with:  python manage.py test tests.test_working_entries
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


# ── the client's own answer ─────────────────────────────────────────────────

class _FakeOrder(SimpleNamespace):
    pass


def _fake_ib_module():
    mod = MagicMock()
    mod.MarketOrder.side_effect = lambda a, q: _FakeOrder(
        action=a, totalQuantity=q, orderType="MKT", transmit=True, orderId=0)
    mod.LimitOrder.side_effect = lambda a, q, p: _FakeOrder(
        action=a, totalQuantity=q, lmtPrice=p, orderType="LMT",
        transmit=True, orderId=0)
    mod.StopOrder.side_effect = lambda a, q, p: _FakeOrder(
        action=a, totalQuantity=q, auxPrice=p, orderType="STP",
        transmit=True, orderId=0)
    return mod


def _trader_placing(status, filled):
    """An IBKRTrader whose parent comes back in `status` with `filled` done."""
    from bot_program.engine.ibkr_client import IBKRTrader
    t = IBKRTrader(host="h", port=4004, client_id=7, account_id="DU111",
                   timeout=0.1)
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.managedAccounts.return_value = ["DU111"]
    t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
    t._ib.client = SimpleNamespace(getReqId=lambda: 4242)

    def _bracket(action, qty, limitPrice=None, takeProfitPrice=None,
                 stopLossPrice=None):
        ex = "SELL" if action == "BUY" else "BUY"
        return [
            _FakeOrder(action=action, totalQuantity=qty, orderType="LMT",
                       transmit=True, orderId=1),
            _FakeOrder(action=ex, totalQuantity=qty, lmtPrice=takeProfitPrice,
                       orderType="LMT", transmit=True, orderId=2),
            _FakeOrder(action=ex, totalQuantity=qty, auxPrice=stopLossPrice,
                       orderType="STP", transmit=True, orderId=3),
        ]

    t._ib.bracketOrder.side_effect = _bracket
    placed = []

    def _place(contract, order):
        placed.append(order)
        order.orderId = getattr(order, "orderId", 0) or (100 + len(placed))
        if len(placed) == 1:
            return SimpleNamespace(
                order=order,
                orderStatus=SimpleNamespace(status=status, filled=filled,
                                            avgFillPrice=100.0 if filled else 0),
                log=[])
        return SimpleNamespace(
            order=order,
            orderStatus=SimpleNamespace(status="PreSubmitted", filled=0,
                                        avgFillPrice=0),
            log=[])

    t._ib.placeOrder.side_effect = _place
    t._placed = placed
    return t


def _order(t, **kw):
    from bot_program.engine import ibkr_client
    with patch.object(ibkr_client, "_ib", _fake_ib_module()), \
            patch.object(t, "_connect", return_value=True), \
            patch.object(t, "_build_contract", return_value=MagicMock()):
        return t.market_order("AAPL", "BUY", 10, **kw)


class AnUnfilledParentIsNotAFillTests(TestCase):

    def test_presubmitted_with_nothing_filled_answers_working(self):
        t = _trader_placing("PreSubmitted", 0)
        res = _order(t, stop_loss=95.0, take_profit=110.0)
        self.assertEqual(res["status"], "WORKING")
        self.assertTrue(res["working"])
        self.assertEqual(float(res["executedQty"]), 0.0)

    def test_a_working_parent_claims_no_protection(self):
        """protectedOnFill turns OFF bot-side management. Claiming it for a
        position that does not exist is how the fill arrives unwatched."""
        t = _trader_placing("Submitted", 0)
        res = _order(t, stop_loss=95.0, take_profit=110.0)
        self.assertNotIn("protectedOnFill", res)
        # The legs are still reported, so the row can cancel them later.
        self.assertEqual(len(res["protectiveOrders"]), 2)
        self.assertTrue(res["protectiveStopId"])

    def test_a_real_fill_is_unchanged(self):
        t = _trader_placing("Filled", 10)
        res = _order(t, stop_loss=95.0, take_profit=110.0)
        self.assertEqual(res["status"], "FILLED")
        self.assertNotIn("working", res)
        self.assertTrue(res["protectedOnFill"])
        self.assertEqual(float(res["executedQty"]), 10.0)


# ── order_status ────────────────────────────────────────────────────────────

class OrderStatusTests(SimpleTestCase):

    def _t(self, *, open_trades=(), trades=(), completed=()):
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader(host="h", port=4004, client_id=7, timeout=0.1)
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True

        def _mk(rows):
            return [SimpleNamespace(
                order=SimpleNamespace(orderId=oid),
                orderStatus=SimpleNamespace(status=st, filled=f,
                                            avgFillPrice=px, remaining=0))
                for oid, st, f, px in rows]

        t._ib.openTrades.return_value = _mk(open_trades)
        t._ib.trades.return_value = _mk(trades)
        t._ib.reqCompletedOrders.return_value = _mk(completed)
        # Explicit: an "unknown" answer must come from all three sources
        # genuinely knowing nothing, not from a MagicMock that raises.
        t._ib.reqExecutions.return_value = []
        return t

    def test_a_working_order_is_working(self):
        t = self._t(open_trades=[(101, "Submitted", 0, 0)])
        self.assertEqual(t.order_status("101")["state"], "working")

    def test_a_filled_order_is_filled_with_its_price(self):
        t = self._t(trades=[(101, "Filled", 10, 99.5)])
        st = t.order_status("101")
        self.assertEqual(st["state"], "filled")
        self.assertEqual(st["filled"], 10.0)
        self.assertEqual(st["avgPrice"], 99.5)

    def test_a_cancelled_order_with_nothing_filled_is_dead(self):
        t = self._t(trades=[(101, "Cancelled", 0, 0)])
        self.assertEqual(t.order_status("101")["state"], "dead")

    def test_a_part_filled_then_cancelled_order_is_a_fill(self):
        t = self._t(trades=[(101, "Cancelled", 4, 99.0)])
        st = t.order_status("101")
        self.assertEqual(st["state"], "filled")
        self.assertEqual(st["filled"], 4.0)

    def test_completed_orders_are_deliberately_not_consulted(self):
        """IBKR's completedOrder message carries permId, not orderId, so
        ib_insync leaves order.orderId at 0 and a lookup by the id this
        platform stores can NEVER match. A source that always misses is
        worse than none: it reads as having been checked."""
        t = self._t(completed=[(101, "Filled", 10, 100.25)])
        self.assertEqual(t.order_status("101")["state"], "unknown")
        t._ib.reqCompletedOrders.assert_not_called()

    def test_an_id_nobody_knows_is_unknown_not_dead(self):
        t = self._t()
        self.assertEqual(t.order_status("999")["state"], "unknown")

    def test_unreachable_is_none(self):
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader(timeout=0.1)
        with patch.object(t, "_connect", return_value=False):
            self.assertIsNone(t.order_status("101"))


# ── the tick that owns a working row ───────────────────────────────────────

def _user(name):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, name="WORK"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode="live",
        symbols=["NVDA"], capital=Decimal("10000"), enabled=True)


def _working_trade(cfg, **meta):
    from bot_program.models import AssetBotTrade
    metadata = {"entry_working": True, "qty_requested": 10.0,
                "protective_order_ids": ["12", "13"],
                "protective_stop_id": "13", "protected": False,
                "entry_working_since": "2026-09-06T00:00:00+00:00"}
    metadata.update(meta)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="NVDA", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=False, broker_order_id="101",
        metadata=metadata)


# What the ACCOUNT holds, as get_positions reports it. Ten shares is
# exactly what the working row asked for; five is less than the claims
# against it, so five cannot be attributed to this row.
HELD_10 = [{"symbol": "NVDA", "qty": 10.0, "side": "BUY", "sec_type": "STK"}]
HELD_5 = [{"symbol": "NVDA", "qty": 5.0, "side": "BUY", "sec_type": "STK"}]


#: "not passed" — distinct from an explicit None, which is what the broker
#: answers when its resting orders COULD NOT BE READ. Conflating the two made
#: a test that meant "unreadable" silently assert against a healthy read.
_DEFAULT = object()


def _client(order_state, *, resting=_DEFAULT, position=None, positions=None):
    c = MagicMock()
    c.ticker.return_value = {"lastPrice": "101", "symbol": "NVDA"}
    c.order_status.return_value = order_state
    c.resting_order_ids.return_value = ({"12", "13"} if resting is _DEFAULT
                                        else resting)
    c.position_avg_cost.return_value = position
    # The account's positions, used to ATTRIBUTE an unknown order id. A
    # position no row can be matched to is never booked onto one.
    c.get_positions.return_value = positions if positions is not None else []
    c.cancel_order.return_value = True
    return c


class TheTickPollsAWorkingEntryTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("work_u")
        self.cfg = _cfg(self.user)

    def _tick(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(self.cfg).manage_positions()

    def test_a_fill_becomes_a_position_at_the_brokers_price_and_size(self):
        trade = _working_trade(self.cfg)
        self._tick(_client({"state": "filled", "filled": 10.0,
                            "avgPrice": 99.75, "status": "Filled"}))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(float(trade.entry_price), 99.75)
        self.assertEqual(float(trade.qty), 10.0)
        self.assertNotIn("entry_working", trade.metadata)
        self.assertEqual(trade.metadata["fill_source"], "broker")
        # The stop leg was seen resting, so protection is claimed NOW.
        self.assertTrue(trade.metadata["protected"])

    def test_a_fill_whose_stop_is_not_resting_is_managed_by_the_bot(self):
        trade = _working_trade(self.cfg)
        self._tick(_client({"state": "filled", "filled": 10.0,
                            "avgPrice": 99.75, "status": "Filled"},
                           resting={"12"}))     # the stop, 13, never armed
        trade.refresh_from_db()
        self.assertFalse(trade.metadata["protected"])
        self.assertIn("not seen resting", trade.metadata["protection_note"])

    def test_a_dead_order_cancels_the_row_and_grades_nothing(self):
        trade = _working_trade(self.cfg)
        self._tick(_client({"state": "dead", "filled": 0.0, "avgPrice": 0,
                            "status": "Cancelled"}))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CANCELED")
        self.assertEqual(trade.outcome, "")          # nothing traded
        self.assertEqual(float(trade.pnl), 0.0)
        self.assertIn("entry_withdrawn_reason", trade.metadata)

    def test_a_partial_fill_withdraws_the_remainder_and_the_legs(self):
        trade = _working_trade(self.cfg)
        client = _client({"state": "working", "filled": 4.0,
                          "avgPrice": 99.5, "status": "Submitted"})
        # The post-cancel read is what the fill is booked from: units can
        # print while the remainder is being withdrawn.
        client.order_status.side_effect = [
            {"state": "working", "filled": 4.0, "avgPrice": 99.5,
             "status": "Submitted"},
            {"state": "filled", "filled": 4.0, "avgPrice": 99.5,
             "status": "Cancelled"},
        ]
        self._tick(client)
        trade.refresh_from_db()
        self.assertEqual(float(trade.qty), 4.0)
        self.assertEqual(float(trade.entry_price), 99.5)
        self.assertFalse(trade.metadata["protected"])
        self.assertIn("over-cover", trade.metadata["protection_note"])
        cancelled = [c.args[0] for c in client.cancel_order.call_args_list]
        self.assertIn("101", cancelled)              # the unfilled remainder
        self.assertIn("13", cancelled)               # and its legs

    def test_a_still_working_order_inside_its_window_is_left_alone(self):
        from django.utils import timezone
        trade = _working_trade(
            self.cfg, entry_working_since=timezone.now().isoformat())
        client = _client({"state": "working", "filled": 0.0, "avgPrice": 0,
                          "status": "PreSubmitted"})
        self._tick(client)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["entry_working"])
        client.cancel_order.assert_not_called()

    def test_an_order_that_outlives_its_window_is_withdrawn(self):
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.asset_engine.base import AssetBot
        old = timezone.now() - timedelta(
            hours=AssetBot.ENTRY_WORKING_MAX_HOURS + 2)
        trade = _working_trade(self.cfg, entry_working_since=old.isoformat())
        client = _client({"state": "working", "filled": 0.0, "avgPrice": 0,
                          "status": "PreSubmitted"})
        client.order_status.side_effect = [
            {"state": "working", "filled": 0.0, "avgPrice": 0,
             "status": "PreSubmitted"},
            {"state": "dead", "filled": 0.0, "avgPrice": 0,
             "status": "Cancelled"},       # the post-cancel proof
        ]
        self._tick(client)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CANCELED")
        self.assertIn("still working after", trade.metadata["entry_withdrawn_reason"])

    def test_an_unreadable_broker_leaves_the_row_working(self):
        trade = _working_trade(self.cfg)
        client = _client(None)
        self._tick(client)
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["entry_working"])
        client.cancel_order.assert_not_called()

    def test_an_unknown_id_is_decided_by_an_ATTRIBUTABLE_position(self):
        """The broker does not know the id (another clientId placed it, or
        this session restarted). An account position that IS attributable to
        this row settles it."""
        trade = _working_trade(self.cfg)
        self._tick(_client({"state": "unknown", "filled": 0.0, "avgPrice": 0,
                            "status": ""},
                           positions=HELD_10,
                           position={"qty": 10.0, "side": "BUY",
                                     "avg_cost": 100.5, "sec_type": "STK"}))
        trade.refresh_from_db()
        self.assertNotIn("entry_working", trade.metadata)
        self.assertEqual(float(trade.entry_price), 100.5)
        self.assertEqual(trade.metadata["fill_source"], "position")

    def test_an_unknown_id_over_an_unattributable_position_waits_and_warns(self):
        """Another row (or a hand-bought lot) claims the same symbol, so the
        account total cannot say whose units they are. Booking them here
        would put someone else's shares on this row."""
        from bot_program.models import AssetBotTrade
        other = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="NVDA", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=False, metadata={})
        trade = _working_trade(self.cfg)
        self._tick(_client({"state": "unknown", "filled": 0.0, "avgPrice": 0,
                            "status": ""},
                           positions=HELD_5,      # only 5 held, 10 claimed
                           position={"qty": 5.0, "side": "BUY",
                                     "avg_cost": 100.5, "sec_type": "STK"}))
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["entry_working"])
        self.assertTrue(trade.metadata["entry_unresolved_notified"])
        self.assertEqual(other.status, "OPEN")

    def test_an_unknown_id_with_a_flat_account_is_never_withdrawn(self):
        """Flat is NOT proof the order never filled: the entry may have
        filled and its GTC stop may have closed the position again."""
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.asset_engine.base import AssetBot
        old = timezone.now() - timedelta(
            hours=AssetBot.ENTRY_WORKING_MAX_HOURS + 2)
        trade = _working_trade(self.cfg, entry_working_since=old.isoformat())
        client = _client({"state": "unknown", "filled": 0.0, "avgPrice": 0,
                          "status": ""}, positions=[], position={})
        self._tick(client)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["entry_working"])
        client.cancel_order.assert_not_called()

    def test_a_working_row_is_never_marked_or_stopped_out(self):
        """No position exists, so SL/TP arithmetic on it would close a
        trade that was never opened."""
        trade = _working_trade(self.cfg)
        client = _client({"state": "working", "filled": 0.0, "avgPrice": 0,
                          "status": "PreSubmitted"})
        from django.utils import timezone
        trade.metadata = {**trade.metadata,
                          "entry_working_since": timezone.now().isoformat()}
        trade.save(update_fields=["metadata"])
        client.ticker.return_value = {"lastPrice": "1", "symbol": "NVDA"}
        self._tick(client)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")       # not closed at 1.00
        client.market_order.assert_not_called()


# ── the SEAM: an unfilled order really does produce a WORKING row ──────────

class TheEntryPathBooksAWorkingRowTests(TestCase):
    """The whole state machine hangs on the entry path recognising
    `working`. Every other test here starts from a row that already carries
    the metadata, so without this one an inverted guard in the booking code
    would pass the suite and restore the original defect verbatim.
    """

    def setUp(self):
        from instruments.models import Instrument
        from signals.models import Signal
        from signals.models_control import RuleControl
        self.user = _user("seam_u")
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        from bot_program.models import AssetBotConfig
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="SEAM", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        # A live entry needs a promoted rule: an unregistered one is
        # confined to paper whatever the config says, and paper never
        # reaches a broker.
        RuleControl.objects.get_or_create(
            rule_name="r1", defaults={"promotion_stage": "live_full"})
        Signal.objects.create(
            instrument=self.inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="d", rule_name="r1",
            score=0.9, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), is_active=True)

    def _scan(self, order):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100"}
        client.market_order.return_value = order
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")
        return AssetBotTrade.objects.filter(config=self.cfg,
                                            symbol="AAPL").first()

    def test_an_unfilled_order_books_a_working_row_that_claims_nothing(self):
        trade = self._scan({
            "orderId": "101", "status": "WORKING", "working": True,
            "executedQty": "0", "avgPrice": "0",
            "protectiveOrders": ["12", "13"], "protectiveStopId": "13",
        })
        self.assertIsNotNone(trade)
        self.assertTrue(trade.metadata["entry_working"])
        self.assertFalse(trade.metadata["protected"])
        self.assertEqual(trade.metadata["fill_source"], "pending")
        self.assertIn("entry_working_since", trade.metadata)
        self.assertEqual(trade.broker_order_id, "101")
        # And the operator is NOT told a position opened.
        from alerts.models import Notification
        self.assertFalse(Notification.objects.filter(
            user=self.user, title__icontains="opened").exists())

    def test_a_filled_order_books_an_ordinary_protected_row(self):
        """The guard must not swallow real fills."""
        trade = self._scan({
            "orderId": "102", "status": "FILLED", "executedQty": "5",
            "avgPrice": "100.25", "protectedOnFill": True,
            "protectiveOrders": ["12", "13"], "protectiveStopId": "13",
        })
        self.assertIsNotNone(trade)
        self.assertNotIn("entry_working", trade.metadata)
        self.assertTrue(trade.metadata["protected"])
        self.assertEqual(float(trade.entry_price), 100.25)


# ── the consumers that must not touch a working row ────────────────────────

class ReconciliationLeavesWorkingEntriesAloneTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("rec_work_u")
        self.cfg = _cfg(self.user, name="RECWORK")

    def test_a_working_row_is_not_closed_as_an_orphan(self):
        """The broker rightly reports no position. Closing the row here
        cancels the legs of a parent that then fills naked."""
        from bot_program.reconcile_asset import reconcile_user
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.get_positions.return_value = []       # nothing at the broker
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            out = reconcile_user(self.user)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out.get("entry_working"), 1)
        client.cancel_order.assert_not_called()

    def test_a_filled_row_is_still_reconciled(self):
        """The guard must not switch reconciliation off for real rows."""
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import reconcile_user
        trade = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="NVDA", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=False, metadata={})
        client = MagicMock()
        client.get_positions.return_value = []
        client.ticker.return_value = {"lastPrice": "101"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            out = reconcile_user(self.user)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_as_orphan"], 1)


class TheKillSwitchWithdrawsAWorkingEntryTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("kill_work_u")
        self.cfg = _cfg(self.user, name="KILLWORK")

    def test_flatten_withdraws_the_order_instead_of_selling(self):
        """A market close against a position that does not exist opens the
        reverse one — and leaves the queued parent to fill afterwards."""
        from bot_program.engine.kill_switch import _close_asset_trade
        from django.utils import timezone
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.order_status.return_value = {"state": "dead", "filled": 0.0,
                                            "avgPrice": 0,
                                            "status": "Cancelled"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_asset_trade(trade, timezone.now())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CANCELED")
        client.market_order.assert_not_called()
        self.assertIn("EMERGENCY FLATTEN",
                      trade.metadata["entry_withdrawn_reason"])

    def test_an_unwithdrawable_order_raises_rather_than_lying(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        from django.utils import timezone
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.cancel_order.side_effect = RuntimeError("socket gone")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            with self.assertRaises(RuntimeError):
                _close_asset_trade(trade, timezone.now())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["entry_working"])


class WithdrawingByHandTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("hand_work_u")
        self.cfg = _cfg(self.user, name="HANDWORK")

    def test_the_preview_offers_withdraw_and_invents_no_pnl(self):
        from bot_program.manual_close import preview_close
        trade = _working_trade(self.cfg)
        out = preview_close(self.user, trade)
        self.assertEqual(out["action"], "withdraw")
        self.assertTrue(out["working"])
        self.assertIsNone(out["pnl"])
        self.assertIsNone(out["mark"])

    def test_executing_it_withdraws_the_order(self):
        from bot_program.manual_close import execute_close
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.order_status.return_value = {"state": "dead", "filled": 0.0,
                                            "avgPrice": 0,
                                            "status": "Cancelled"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            out = execute_close(self.user, trade, pin_ok=True)
        trade.refresh_from_db()
        self.assertTrue(out.get("withdrawn"))
        self.assertEqual(trade.status, "CANCELED")
        client.market_order.assert_not_called()


class TheCancelProvesItselfInTheClientTests(SimpleTestCase):
    """ib_insync writes PendingCancel into the order SYNCHRONOUSLY inside
    cancelOrder (ib.py:697-706) and PendingCancel is not a done state, so an
    immediate re-read ALWAYS finds the order still open. A caller that read
    the status straight after cancelling could therefore never see a
    confirmed cancellation — every withdrawal would report failure and no
    queued order could ever be withdrawn. The client waits and answers on
    what TWS says.
    """

    def _t(self, statuses):
        """A trader whose order goes through `statuses` on each read."""
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader(host="h", port=4004, client_id=7, timeout=0.1)
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.sleep.return_value = None
        seq = list(statuses)

        def _open():
            if not seq:
                return []
            st, filled = seq.pop(0)
            if st is None:
                return []
            return [SimpleNamespace(
                order=SimpleNamespace(orderId=101),
                orderStatus=SimpleNamespace(status=st, filled=filled,
                                            avgFillPrice=0, remaining=0))]

        t._ib.openTrades.side_effect = _open
        t._ib.trades.return_value = []
        return t

    def test_a_confirmed_cancellation_answers_true(self):
        t = self._t([("Submitted", 0), ("Cancelled", 0)])
        self.assertTrue(t.cancel_order("101"))
        t._ib.sleep.assert_called()          # TWS was given its turn

    def test_pending_cancel_alone_is_not_confirmation(self):
        """The synchronous PendingCancel write must not be read as done."""
        t = self._t([("Submitted", 0), ("PendingCancel", 0)])
        self.assertFalse(t.cancel_order("101"))

    def test_an_order_gone_from_the_session_counts_as_cancelled(self):
        t = self._t([("Submitted", 0), (None, 0)])
        self.assertTrue(t.cancel_order("101"))

    def test_a_fill_in_the_race_is_not_a_cancellation(self):
        t = self._t([("Submitted", 0), ("Filled", 10)])
        self.assertFalse(t.cancel_order("101"))

    def test_inactive_is_a_refusal_not_a_working_order(self):
        """IBKR parks a refused order as Inactive and ib_insync leaves it in
        openTrades forever; reading that as live would keep a dead order
        alive in every consumer."""
        t = self._t([("Inactive", 0)])
        self.assertEqual(t.order_status("101")["state"], "dead")


class ACancelThatCannotBeProvenIsNotACancelTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("proof_work_u")
        self.cfg = _cfg(self.user, name="PROOFWORK")

    def test_an_order_still_working_after_the_cancel_keeps_the_row(self):
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.order_status.return_value = {"state": "working", "filled": 0.0,
                                            "avgPrice": 0,
                                            "status": "Submitted"}
        self.assertFalse(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["entry_working"])

    def test_an_order_that_filled_during_the_cancel_keeps_the_row(self):
        """It is a position now. The next poll books it; marking the row
        CANCELED would hide real units."""
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.order_status.return_value = {"state": "filled", "filled": 10.0,
                                            "avgPrice": 99.0,
                                            "status": "Filled"}
        self.assertFalse(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["entry_working"])

    def test_a_client_that_cannot_cancel_never_marks_the_row_canceled(self):
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        client = MagicMock(spec=["ticker"])       # no cancel_order at all
        self.assertFalse(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_an_unreadable_broker_after_the_cancel_keeps_the_row(self):
        """'Could not look' must never be read as 'gone' — the row is about
        to record that nothing was traded."""
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.cancel_order.return_value = True
        client.order_status.return_value = None      # socket died
        self.assertFalse(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_cancel_the_broker_could_not_find_keeps_the_row(self):
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.cancel_order.return_value = False     # not found / not mine
        self.assertFalse(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_leaked_gtc_leg_is_recorded_and_alerted_even_when_the_row_cancels(self):
        """The parent is confirmed dead so the row IS canceled — but a leg
        that is good-till-cancelled and was not confirmed rests for days,
        and a resting exit against a flat book OPENS a position."""
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        client = MagicMock()
        client.order_status.return_value = {"state": "dead", "filled": 0.0,
                                            "avgPrice": 0,
                                            "status": "Cancelled"}
        client.cancel_order.side_effect = (
            lambda oid: True if oid == "101" else False)   # legs refuse
        # notify_staff reaches STAFF users, so there must be one for the
        # alert to land anywhere — the platform's own rule, not the test's.
        User.objects.create_user("leak_staff", password="x", is_staff=True)
        self.assertTrue(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CANCELED")
        self.assertTrue(trade.metadata["protective_legs_unconfirmed"])
        from alerts.models import Notification
        self.assertTrue(Notification.objects.filter(
            title__icontains="may still rest").exists())

    def test_a_row_with_no_order_id_is_never_marked_canceled(self):
        """Without an id the parent can neither be cancelled nor read.
        Falling through would cancel the protective legs and record
        "nothing traded" over an order that is still queued and about to
        fill NAKED, into a row nothing walks any more."""
        from bot_program.asset_engine.base import cancel_working_entry
        trade = _working_trade(self.cfg)
        trade.broker_order_id = ""            # the manual lane's old shape
        trade.save(update_fields=["broker_order_id"])
        client = MagicMock()
        client.order_status.return_value = {"state": "dead", "filled": 0.0,
                                            "avgPrice": 0,
                                            "status": "Cancelled"}
        self.assertFalse(cancel_working_entry(trade, client, reason="test"))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["entry_working"])
        # And crucially: the LEGS were not touched, so the parent that may
        # still fill keeps its stop and target.
        client.cancel_order.assert_not_called()

    def test_the_manual_lane_stores_the_brokers_order_id(self):
        """It used to drop it, which is what made a hand-taken live row
        impossible to withdraw, look up or modify at the broker."""
        import inspect

        from bot_program import manual_trade
        src = inspect.getsource(manual_trade)
        self.assertIn("broker_order_id=str(broker_order_id or \"\")", src)
        self.assertIn('broker_order_id=str(res.get("orderId") or "")', src)

    def test_no_tax_lot_is_opened_until_the_fill(self):
        """A lot is a cost basis for units the account owns. close_lots_for
        consumes open lots FIFO by symbol, not by source trade, so a lot
        minted for a queued order would be consumed by the next real close
        and report a gain against shares nobody bought.

        This drives the ENTRY PATH, not a hand-made row: the earlier version
        asserted on a row built with objects.create, which never calls
        open_lot at all, so the guard could have been deleted with the suite
        still green."""
        from bot_program.models import AssetBotTrade
        from bot_program.tax_lot_models import TaxLot
        from signals.models import Signal
        from signals.models_control import RuleControl
        from instruments.models import Instrument
        from bot_program.asset_engine.stock_bot import StockBot

        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        RuleControl.objects.get_or_create(
            rule_name="r_lot", defaults={"promotion_stage": "live_full"})
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="d", rule_name="r_lot",
            score=0.9, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), is_active=True)
        self.cfg.symbols = ["AAPL"]
        self.cfg.save(update_fields=["symbols"])

        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100"}
        client.market_order.return_value = {
            "orderId": "301", "status": "WORKING", "working": True,
            "executedQty": "0", "avgPrice": "0",
            "protectiveOrders": ["12", "13"], "protectiveStopId": "13"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            StockBot(self.cfg).scan_symbol("AAPL")
        row = AssetBotTrade.objects.get(config=self.cfg, symbol="AAPL")
        self.assertTrue(row.metadata["entry_working"])
        self.assertFalse(TaxLot.objects.filter(source_trade=row).exists())

        # ...and the lot appears when the fill is booked, once.
        client.order_status.return_value = {"state": "filled", "filled": 5.0,
                                            "avgPrice": 99.5,
                                            "status": "Filled"}
        client.resting_order_ids.return_value = {"12", "13"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            StockBot(self.cfg).manage_positions()
        row.refresh_from_db()
        self.assertNotIn("entry_working", row.metadata)
        lots = TaxLot.objects.filter(source_trade=row)
        self.assertEqual(lots.count(), 1)
        self.assertEqual(float(lots.first().cost_basis_per_unit), 99.5)


class ACrossTickFillIsFoundInTheExecutionsTests(SimpleTestCase):
    """The trading session is released after every task, so the tick that
    polls a queued order is ALWAYS on a socket opened after the order was
    placed — and a FILLED order is in neither openTrades nor this session's
    trade table. Without a third source every cross-tick fill answered
    "unknown", which for options (whose position list cannot be attributed)
    meant the row could never resolve at all.
    """

    def _t(self, executions):
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader(host="h", port=4004, client_id=7, timeout=0.1)
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.openTrades.return_value = []
        t._ib.trades.return_value = []
        t._ib.reqExecutions.return_value = [
            SimpleNamespace(execution=SimpleNamespace(
                orderId=oid, shares=q, price=p))
            for oid, q, p in executions]
        return t

    def test_a_fill_only_the_executions_know_is_found(self):
        t = self._t([(101, 5.0, 99.5)])
        st = t.order_status("101")
        self.assertEqual(st["state"], "filled")
        self.assertEqual(st["filled"], 5.0)
        self.assertEqual(st["avgPrice"], 99.5)

    def test_several_prints_are_size_weighted(self):
        """A market order can print in pieces; the row must book the real
        average, not the first or the last price."""
        t = self._t([(101, 4.0, 100.0), (101, 6.0, 105.0)])
        st = t.order_status("101")
        self.assertEqual(st["filled"], 10.0)
        self.assertEqual(st["avgPrice"], 103.0)

    def test_another_orders_executions_are_not_borrowed(self):
        t = self._t([(999, 5.0, 99.5)])
        self.assertEqual(t.order_status("101")["state"], "unknown")

    def test_completed_orders_are_still_not_consulted(self):
        t = self._t([])
        self.assertEqual(t.order_status("101")["state"], "unknown")
        t._ib.reqCompletedOrders.assert_not_called()


class AnUnreadableSnapshotDoesNotDisarmTheBrokerTests(TestCase):
    """At the fill, "could not look" is not "the bracket did not arm". Of the
    two ways to be wrong only one is unbounded: saying protected=False while
    a GTC leg really rests arms bot-side exits beside it, and _close_trade
    goes to market BEFORE stripping legs — two exits, account reversed. The
    other way is corrected by the next tick's vanished-stop check.
    """

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("unread_u")
        self.cfg = _cfg(self.user, name="UNREAD")

    def _tick(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(self.cfg).manage_positions()

    def test_an_unreadable_resting_read_leaves_the_broker_in_charge(self):
        trade = _working_trade(self.cfg)
        self._tick(_client({"state": "filled", "filled": 10.0,
                            "avgPrice": 99.75, "status": "Filled"},
                           resting=None))
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self.assertIn("unreadable", trade.metadata["protection_note"])

    def test_a_leg_that_will_not_cancel_keeps_the_broker_in_charge(self):
        """The stop did not arm but the target rests: arming bot-side exits
        beside it is the double close its sibling refuses to create."""
        trade = _working_trade(self.cfg)
        client = _client({"state": "filled", "filled": 10.0,
                          "avgPrice": 99.75, "status": "Filled"},
                         resting={"12"})          # target rests, stop does not
        client.cancel_order.return_value = False  # and will not come down
        self._tick(client)
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self.assertTrue(trade.metadata["protective_legs_unconfirmed"])
        client.cancel_order.assert_any_call("12")
