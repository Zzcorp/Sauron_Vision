"""Break-even and trailing have never moved a stop on IBKR.

Two stacked bugs, and the first hid the second.

`_snap_to_tick(price, min_tick, *, widen)` takes `widen` keyword-only with
no default, and `modify_protective` called it with two positional
arguments. Every IBKR stop move raised TypeError; the outer `except`
swallowed it and answered `ok: False`. The row was not marked
`stop_rules_inert` either — that only happens when a client exposes no
mover at all — so the position read as managed while nothing managed it.
Options and CFDs route to IBKR unconditionally.

Repairing that alone starts losing money. IBKR never recorded
`protectiveStopId`, so the caller walks `protective_order_ids` — a flat
list in PLACEMENT order — and takes the first leg that answers ok. IBKR
places the target first (`bracketOrder` yields parent, takeProfit,
stopLoss), so that leg is the TAKE-PROFIT, and the LMT branch happily
wrote the break-even price into `lmtPrice`: a sell limit below the mark on
a long, filled on the next tick and booked as a take-profit, with the stop
never touched.

So both halves are tested here, because either alone is worse than
neither: the stop moves, and the target refuses to.

Run with:  python manage.py test tests.test_ibkr_stop_moves
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _trader():
    from bot_program.engine.ibkr_client import IBKRTrader
    return IBKRTrader(timeout=0.1, account_id="DU111")


class _Order(SimpleNamespace):
    """An ib_insync Order is a plain attribute bag."""


def _resting(t, *orders, min_tick=0.01, accept_status="Submitted"):
    """Wire a trader whose session holds `orders` as open legs."""
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.managedAccounts.return_value = ["DU111"]
    t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=min_tick)]
    t._ib.openTrades.return_value = [
        SimpleNamespace(order=o, contract=SimpleNamespace(symbol="AAPL"))
        for o in orders]

    # placeOrder is NON-BLOCKING, so the client re-reads the leg before it
    # will claim the move landed. A MagicMock is not good enough here: the
    # whole point of the check is that a leg which did not reach "resting"
    # is a refusal, so the fake has to say which it is.
    def _place(contract, order, status="Submitted"):
        return SimpleNamespace(
            order=order,
            orderStatus=SimpleNamespace(status=accept_status, filled=0),
            log=[])

    t._ib.placeOrder.side_effect = _place
    return t


def _stop_leg(oid=3, action="SELL", price=95.0):
    return _Order(orderId=oid, action=action, orderType="STP",
                  auxPrice=price, account="DU111")


def _target_leg(oid=2, action="SELL", price=115.0):
    return _Order(orderId=oid, action=action, orderType="LMT",
                  lmtPrice=price, account="DU111")


class TheStopActuallyMovesTests(SimpleTestCase):
    """Every call used to raise TypeError and report ok=False."""

    def test_a_stop_move_succeeds(self):
        t = _resting(_trader(), _stop_leg())
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.0)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["price"], 99.0)

    def test_the_new_price_reaches_the_order(self):
        """ok=True while auxPrice still holds the old level would be the
        same silent non-move wearing a success shape."""
        leg = _stop_leg(price=95.0)
        t = _resting(_trader(), leg)
        with patch.object(t, "_connect", return_value=True):
            t.modify_protective("3", 99.0)
        self.assertEqual(leg.auxPrice, 99.0)
        self.assertTrue(t._ib.placeOrder.called)

    def test_a_long_stop_rounds_DOWN_onto_the_tick(self):
        """Widen, never tighten. A long's stop rests below and must round
        away from the position — rounding up moves it closer and fires it
        earlier than the operator asked for."""
        t = _resting(_trader(), _stop_leg(action="SELL"), min_tick=0.05)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.03)
        self.assertEqual(res["price"], 99.00)

    def test_a_short_stop_rounds_UP_onto_the_tick(self):
        """Mirrored: a short is closed by a BUY and its stop rests above."""
        t = _resting(_trader(), _stop_leg(action="BUY"), min_tick=0.05)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.03)
        self.assertEqual(res["price"], 99.05)

    def test_an_unreadable_tick_is_refused_not_guessed(self):
        """The entry path refuses to bracket without a tick; moving one
        without a tick is the same bet. TWS rejects an off-tick price with
        error 110, and a rejected stop is a naked position that still looks
        protected."""
        t = _resting(_trader(), _stop_leg(), min_tick=0)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.0)
        self.assertFalse(res["ok"])
        self.assertIn("minTick", res["reason"])
        self.assertFalse(t._ib.placeOrder.called)


class TheTargetIsRefusedTests(SimpleTestCase):
    """The bug the repair would otherwise have armed."""

    def test_a_limit_leg_is_refused(self):
        t = _resting(_trader(), _target_leg())
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("2", 99.0)
        self.assertFalse(res["ok"])
        self.assertIn("take-profit", res["reason"])

    def test_the_target_price_is_left_alone(self):
        """Writing the break-even price into lmtPrice puts a sell limit
        BELOW the mark on a long: filled on the next tick, booked as a
        take-profit, stop never touched."""
        leg = _target_leg(price=115.0)
        t = _resting(_trader(), leg)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("2", 99.0)
        self.assertEqual(leg.lmtPrice, 115.0)
        self.assertFalse(t._ib.placeOrder.called)
        # The reason matters as much as the outcome. Before the repair the
        # price also survived — but only because the TypeError fired first,
        # which is the first bug hiding the second. Asserting WHY it was
        # refused is what keeps this honest once the crash is gone.
        self.assertIn("take-profit", res["reason"])

    def test_refusing_lets_the_caller_walk_on_to_the_stop(self):
        """The caller's loop breaks on the first leg that answers ok. A
        refusal on the target is what lets it reach the stop — which is the
        whole reason this is a refusal and not a best effort."""
        target, stop = _target_leg(), _stop_leg()
        t = _resting(_trader(), target, stop)
        with patch.object(t, "_connect", return_value=True):
            first = t.modify_protective("2", 99.0)
            second = t.modify_protective("3", 99.0)
        self.assertFalse(first["ok"])
        self.assertTrue(second["ok"], second.get("reason"))
        self.assertEqual(target.lmtPrice, 115.0)
        self.assertEqual(stop.auxPrice, 99.0)


class TheStopLegIsNamedAtEntryTests(SimpleTestCase):
    """So nothing downstream has to guess which id is which."""

    def _placed_bracket(self, stop_first=False, bracket_capable=True):
        t = _trader()
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.managedAccounts.return_value = ["DU111"]
        t._ib.reqContractDetails.return_value = [
            SimpleNamespace(minTick=0.01)]
        t._ib.client = SimpleNamespace(getReqId=lambda: 4242)

        def _bracket(action, qty, limitPrice=None, takeProfitPrice=None,
                     stopLossPrice=None):
            if not bracket_capable:
                raise AttributeError("no bracketOrder in this build")
            parent = _Order(action=action, totalQuantity=qty,
                            orderType="MKT", transmit=True, orderId=1)
            tp = _Order(action="SELL", totalQuantity=qty, orderType="LMT",
                        lmtPrice=takeProfitPrice, transmit=True, orderId=2)
            sl = _Order(action="SELL", totalQuantity=qty, orderType="STP",
                        auxPrice=stopLossPrice, transmit=True, orderId=3)
            # Real ib_insync yields (parent, takeProfit, stopLoss).
            return [parent, sl, tp] if stop_first else [parent, tp, sl]

        t._ib.bracketOrder.side_effect = _bracket
        placed = []

        def _place(contract, order):
            placed.append(order)
            # TWS assigns the id at placement; the hand-built fallback
            # arrives with orderId=0, and a leg with no id is never named.
            if not getattr(order, "orderId", 0):
                order.orderId = 100 + len(placed)
            return SimpleNamespace(
                order=order,
                orderStatus=SimpleNamespace(
                    status="Filled" if len(placed) == 1 else "Submitted",
                    filled=order.totalQuantity, avgFillPrice=100.0),
                log=[])

        t._ib.placeOrder.side_effect = _place
        with patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract",
                             return_value=MagicMock()):
            return t.market_order("AAPL", "BUY", 10, stop_loss=95.0,
                                  take_profit=115.0)

    def test_the_stop_leg_is_named(self):
        out = self._placed_bracket()
        self.assertTrue(out.get("protectedOnFill"), out)
        self.assertEqual(str(out.get("protectiveStopId")), "3")

    def test_the_flat_list_still_leads_with_the_target(self):
        """Proving WHY the name is needed: walking this list blind reaches
        the take-profit first."""
        out = self._placed_bracket()
        self.assertEqual([str(x) for x in out["protectiveOrders"]],
                         ["2", "3"])

    def test_the_stop_is_named_by_TYPE_not_by_POSITION(self):
        """Every other fixture here yields (parent, LMT, STP), so a
        refactor to `legs[-1]` would pass them all. This one inverts the
        children: the STP is placed FIRST and must still be the named leg
        while the flat list stays in placement order."""
        out = self._placed_bracket(stop_first=True)
        self.assertEqual(str(out.get("protectiveStopId")), "3")
        self.assertEqual([str(x) for x in out["protectiveOrders"]],
                         ["3", "2"])

    def test_the_hand_built_fallback_also_names_the_stop(self):
        """When ib_insync has no bracketOrder the client builds the legs
        itself from the module-level order classes — a second placement
        path, and it was never exercised."""
        from bot_program.engine import ibkr_client
        mod = MagicMock()
        mod.MarketOrder.side_effect = lambda a, q: _Order(
            action=a, totalQuantity=q, orderType="MKT", transmit=True,
            orderId=0)
        mod.LimitOrder.side_effect = lambda a, q, p: _Order(
            action=a, totalQuantity=q, lmtPrice=p, orderType="LMT",
            transmit=True, orderId=0)
        mod.StopOrder.side_effect = lambda a, q, p: _Order(
            action=a, totalQuantity=q, auxPrice=p, orderType="STP",
            transmit=True, orderId=0)
        with patch.object(ibkr_client, "_ib", mod):
            out = self._placed_bracket(bracket_capable=False)
        self.assertTrue(out.get("protectedOnFill"), out)
        self.assertTrue(out.get("protectiveStopId"),
                        "the fallback path named no stop")


class TWSMustAgreeBeforeWeClaimSuccessTests(SimpleTestCase):
    """`placeOrder` is NON-BLOCKING. Returning ok on the next line reported
    a success TWS had not agreed to — and base.py stamps `breakeven_armed`
    on ok=True, which disarms the rule for the life of the trade. So an
    unverified True left the stop at its original wide level while every
    surface said break-even, and no later tick tried again."""

    def test_a_rejected_modification_is_not_reported_as_moved(self):
        t = _resting(_trader(), _stop_leg(), accept_status="Cancelled")
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.0)
        self.assertFalse(res["ok"])

    def test_an_inactive_leg_is_a_refusal(self):
        """TWS-side rejections surface as Inactive, not as an error."""
        t = _resting(_trader(), _stop_leg(), accept_status="Inactive")
        with patch.object(t, "_connect", return_value=True):
            self.assertFalse(t.modify_protective("3", 99.0)["ok"])

    def test_a_leg_still_pending_a_second_later_is_not_accepted(self):
        """PendingSubmit is assigned LOCALLY the instant placeOrder is
        called, before TWS has said anything at all."""
        t = _resting(_trader(), _stop_leg(), accept_status="PendingSubmit")
        with patch.object(t, "_connect", return_value=True):
            self.assertFalse(t.modify_protective("3", 99.0)["ok"])

    def test_the_client_waits_before_reading_the_status(self):
        """Without the wait every leg reads PendingSubmit and nothing could
        ever succeed — the check would be a blanket refusal."""
        t = _resting(_trader(), _stop_leg())
        with patch.object(t, "_connect", return_value=True):
            t.modify_protective("3", 99.0)
        self.assertTrue(t._ib.sleep.called)


class TheModificationIsInPlaceTests(SimpleTestCase):
    """The method's central safety claim: re-place the SAME resting order,
    never cancel-then-replace (which leaves the position bare) and never
    place a copy (which leaves TWO stops, so the position closes on one and
    OPENS THE OTHER WAY on the other)."""

    def test_the_leg_is_never_cancelled(self):
        t = _resting(_trader(), _stop_leg())
        with patch.object(t, "_connect", return_value=True):
            t.modify_protective("3", 99.0)
        t._ib.cancelOrder.assert_not_called()

    def test_exactly_one_order_is_placed(self):
        t = _resting(_trader(), _stop_leg())
        with patch.object(t, "_connect", return_value=True):
            t.modify_protective("3", 99.0)
        self.assertEqual(t._ib.placeOrder.call_count, 1)

    def test_it_is_the_same_object_carrying_the_same_id(self):
        """A copy would rest alongside the original rather than replace
        it — ib_insync treats a re-placed orderId as a modification."""
        leg = _stop_leg(oid=3)
        t = _resting(_trader(), leg)
        with patch.object(t, "_connect", return_value=True):
            t.modify_protective("3", 99.0)
        self.assertIs(t._ib.placeOrder.call_args[0][1], leg)
        self.assertEqual(leg.orderId, 3)


class TheRefusalBranchesAreRealTests(SimpleTestCase):
    """Alpaca pins its equivalents; IBKR pinned none of them."""

    def test_a_leg_that_is_gone_is_an_answer_not_an_error(self):
        """An order already filled is not a failure — it is the position
        having exited."""
        t = _resting(_trader())
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.0)
        self.assertFalse(res["ok"])
        self.assertIn("not among the open orders", res["reason"])

    def test_an_unknown_order_type_is_refused_rather_than_guessed(self):
        """A TRAIL leg carries its price in neither auxPrice alone nor
        lmtPrice alone, and guessing would move the wrong field."""
        leg = _Order(orderId=3, action="SELL", orderType="TRAIL LIMIT",
                     auxPrice=95.0, lmtPrice=95.0, account="DU111")
        t = _resting(_trader(), leg)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.0)
        self.assertFalse(res["ok"])
        self.assertIn("refusing to guess", res["reason"])
        self.assertFalse(t._ib.placeOrder.called)

    def test_a_price_that_will_not_snap_is_refused(self):
        leg = _stop_leg()
        t = _resting(_trader(), leg)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 0)
        self.assertFalse(res["ok"])
        self.assertEqual(leg.auxPrice, 95.0)
        self.assertFalse(t._ib.placeOrder.called)

    def test_an_ambiguous_account_refuses_before_sending(self):
        """A leg re-placed without an account lands on the session default
        — a stop resting against a book that does not hold the position."""
        from bot_program.engine.ibkr_client import IBKRTrader
        leg = _stop_leg()
        t = _resting(IBKRTrader(timeout=0.1), leg)
        t._ib.managedAccounts.return_value = ["DU111", "DU222"]
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_protective("3", 99.0)
        self.assertFalse(res["ok"])
        self.assertFalse(t._ib.placeOrder.called)
        self.assertEqual(leg.auxPrice, 95.0)


class TheEngineWalksTheLegsForRealTests(TestCase):
    """Everything above tests the client in isolation. This drives
    `base.py`'s actual loop against a real IBKRTrader, because that loop is
    the live path for every row opened BEFORE the stop leg was named — it
    walks `protective_order_ids`, which is flat and in placement order, and
    breaks on the first leg that answers ok."""

    def _row(self, **meta):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user("ibkr_walk_%d" % len(meta),
                                        password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="W", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
            extras={"trail_pct": 5.0})
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), take_profit=Decimal("115"),
            status="OPEN", paper=False, opened_at=timezone.now(),
            metadata=dict(protected=True, **meta))
        return cfg, trade

    def _move(self, trade, cfg, target, stop, mark=120.07):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.ibkr_client import IBKRTrader
        client = _resting(IBKRTrader(timeout=0.1, account_id="DU111"),
                          target, stop, min_tick=0.05)
        with patch.object(client, "_connect", return_value=True):
            moved = StockBot(cfg)._manage_broker_stop(trade, mark, client)
        return moved

    def test_the_blind_walk_reaches_the_stop_past_the_target(self):
        """The target is FIRST in the list. Before the refusal it was also
        the leg that got moved."""
        cfg, trade = self._row(protective_order_ids=["2", "3"])
        target, stop = _target_leg(), _stop_leg()
        self.assertTrue(self._move(trade, cfg, target, stop))
        self.assertEqual(target.lmtPrice, 115.0, "the TARGET was moved")
        self.assertNotEqual(stop.auxPrice, 95.0, "the stop never moved")

    def test_the_named_handle_never_asks_the_target_at_all(self):
        cfg, trade = self._row(protective_order_ids=["2", "3"],
                               protective_stop_id="3")
        target, stop = _target_leg(), _stop_leg()
        self.assertTrue(self._move(trade, cfg, target, stop))
        self.assertEqual(target.lmtPrice, 115.0)

    def test_the_row_records_the_price_the_venue_took(self):
        """A stop is snapped onto the contract's minTick before it is sent,
        so the accepted price can differ from the request by up to a tick.
        Recording the REQUEST left the row, the forensics timeline and the
        operator's "protected at" reading describing a level resting
        nowhere — and it biased the ratchet, because `is_improvement`
        compares the next candidate against this field."""
        from bot_program.models import AssetBotTrade
        cfg, trade = self._row(protective_order_ids=["3"],
                               protective_stop_id="3")
        stop = _stop_leg()
        self.assertTrue(self._move(trade, cfg, _target_leg(), stop))
        row = AssetBotTrade.objects.get(pk=trade.pk)
        # 120.07 * 0.95 = 114.0665, snapped DOWN onto a 0.05 tick.
        self.assertEqual(float(row.stop_loss), 114.05)
        self.assertEqual(stop.auxPrice, 114.05)

    def test_the_audit_keeps_what_was_asked_for_beside_what_rests(self):
        from bot_program.models import AssetBotTrade
        cfg, trade = self._row(protective_order_ids=["3"],
                               protective_stop_id="3")
        self._move(trade, cfg, _target_leg(), _stop_leg())
        moves = (AssetBotTrade.objects.get(pk=trade.pk).metadata
                 or {}).get("stop_moves") or []
        self.assertTrue(moves)
        self.assertEqual(moves[-1]["to"], "114.05")
        self.assertNotEqual(moves[-1]["asked"], moves[-1]["to"])

    def test_a_refused_move_leaves_the_row_alone(self):
        """The row must never claim a level the venue did not accept."""
        from bot_program.models import AssetBotTrade
        cfg, trade = self._row(protective_order_ids=["3"],
                               protective_stop_id="3")
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.ibkr_client import IBKRTrader
        stop = _stop_leg()
        client = _resting(IBKRTrader(timeout=0.1, account_id="DU111"),
                          stop, min_tick=0.05, accept_status="Cancelled")
        with patch.object(client, "_connect", return_value=True):
            moved = StockBot(cfg)._manage_broker_stop(trade, 120.07, client)
        self.assertFalse(moved)
        self.assertEqual(AssetBotTrade.objects.get(pk=trade.pk).stop_loss,
                         Decimal("95"))

    def test_a_refused_move_does_not_arm_breakeven(self):
        """`breakeven_armed` disarms the rule for the life of the trade, so
        stamping it on an unverified move left the stop wide forever."""
        from bot_program.models import AssetBotTrade
        cfg, trade = self._row(protective_order_ids=["3"],
                               protective_stop_id="3")
        cfg.extras = {"breakeven_at_r": 1.0}
        cfg.save(update_fields=["extras"])
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.ibkr_client import IBKRTrader
        client = _resting(IBKRTrader(timeout=0.1, account_id="DU111"),
                          _stop_leg(), min_tick=0.05,
                          accept_status="Cancelled")
        with patch.object(client, "_connect", return_value=True):
            StockBot(cfg)._manage_broker_stop(trade, 120.07, client)
        meta = AssetBotTrade.objects.get(pk=trade.pk).metadata or {}
        self.assertNotIn("breakeven_armed", meta)
