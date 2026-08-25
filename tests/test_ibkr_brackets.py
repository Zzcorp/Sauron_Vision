"""IBKR positions stop going out naked.

OANDA attaches stopLossOnFill/takeProfitOnFill and Alpaca submits a
bracket order class; the IBKR client took the same stop_loss/take_profit
kwargs and DROPPED them, so every IBKR position was protected by nothing
but the five-minute tick loop — a worker crash or an overnight socket
drop left real money unhedged until the loop came back.

Two halves are tested here because half is worse than none: the bracket
itself, and cancel_order — without it a manual flatten sells the
position and leaves the stop resting, and a resting stop against a flat
book opens a brand-new position the other way when it fires.

Run with:  python manage.py test tests.test_ibkr_brackets
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase


def _trader(**kw):
    from bot_program.engine.ibkr_client import IBKRTrader
    return IBKRTrader(timeout=0.1, **kw)


class _FakeOrder(SimpleNamespace):
    """An ib_insync Order stands in as a plain attribute bag."""


def _fake_ib_module(bracket_ids=(11, 12, 13)):
    """A stand-in for the ib_insync module the client imports as _ib."""
    mod = MagicMock()

    def _market(action, qty):
        return _FakeOrder(action=action, totalQuantity=qty,
                          orderType="MKT", transmit=True, orderId=0)

    def _limit(action, qty, price):
        return _FakeOrder(action=action, totalQuantity=qty, lmtPrice=price,
                          orderType="LMT", transmit=True, orderId=0)

    def _stop(action, qty, price):
        return _FakeOrder(action=action, totalQuantity=qty, auxPrice=price,
                          orderType="STP", transmit=True, orderId=0)

    mod.MarketOrder.side_effect = _market
    mod.LimitOrder.side_effect = _limit
    mod.StopOrder.side_effect = _stop
    return mod


def _connected(t, bracket_capable=True):
    """Wire a trader whose _ib answers like a live, filled session."""
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.managedAccounts.return_value = ["DU111"]

    def _bracket(action, qty, limitPrice=None, takeProfitPrice=None,
                 stopLossPrice=None):
        if not bracket_capable:
            raise AttributeError("no bracketOrder in this build")
        parent = _FakeOrder(action=action, totalQuantity=qty,
                            orderType="LMT", transmit=True, orderId=1)
        tp = _FakeOrder(action="SELL" if action == "BUY" else "BUY",
                        totalQuantity=qty, lmtPrice=takeProfitPrice,
                        orderType="LMT", transmit=True, orderId=2)
        sl = _FakeOrder(action="SELL" if action == "BUY" else "BUY",
                        totalQuantity=qty, auxPrice=stopLossPrice,
                        orderType="STP", transmit=True, orderId=3)
        return [parent, tp, sl]

    t._ib.bracketOrder.side_effect = _bracket
    # minTick lives on ContractDetails; a penny tick keeps the equity
    # fixtures reading naturally.
    t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
    t._ib.client = SimpleNamespace(getReqId=lambda: 4242)

    placed = []

    def _place(contract, order):
        placed.append(order)
        oid = getattr(order, "orderId", 0) or (100 + len(placed))
        order.orderId = oid
        # Children rest (Submitted); the parent is the one that fills.
        status = "Filled" if len(placed) == 1 else "Submitted"
        return SimpleNamespace(
            order=order,
            orderStatus=SimpleNamespace(status=status,
                                        filled=order.totalQuantity,
                                        avgFillPrice=100.0),
            log=[])

    t._ib.placeOrder.side_effect = _place
    t._placed = placed
    return t


class BracketSubmissionTests(TestCase):
    def _order(self, t, mod, **kw):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", mod), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract", return_value=MagicMock()):
            return t.market_order("AAPL", "BUY", 10, **kw)

    def test_a_protected_entry_rests_its_stop_at_the_broker(self):
        """The whole point: the position survives this process dying."""
        t = _connected(_trader(account_id="DU111"))
        out = self._order(t, _fake_ib_module(),
                          stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual(len(out["protectiveOrders"]), 2)
        self.assertEqual(len(t._placed), 3)   # parent + two children

    def test_an_unprotected_entry_claims_nothing(self):
        """No levels, no claim — the engine must keep managing it."""
        t = _connected(_trader(account_id="DU111"))
        out = self._order(t, _fake_ib_module())
        self.assertNotIn("protectedOnFill", out)
        self.assertEqual(len(t._placed), 1)

    def test_only_the_last_leg_transmits(self):
        """transmit discipline IS the protection: a parent that starts
        working before its children arrive is the unprotected window the
        bracket exists to close."""
        t = _connected(_trader(account_id="DU111"))
        self._order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertEqual([o.transmit for o in t._placed],
                         [False, False, True])

    def test_the_parent_is_a_market_order_not_the_helpers_limit(self):
        t = _connected(_trader(account_id="DU111"))
        self._order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertEqual(t._placed[0].orderType, "MKT")

    def test_every_leg_carries_the_account(self):
        """A child on the session default is a stop resting against a
        book that does not hold the position — it OPENS one when it
        fires."""
        t = _connected(_trader(account_id="DU111"))
        self._order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertEqual([o.account for o in t._placed], ["DU111"] * 3)

    def test_a_library_without_the_helper_still_protects(self):
        t = _connected(_trader(account_id="DU111"), bracket_capable=False)
        out = self._order(t, _fake_ib_module(),
                          stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual(len(t._placed), 3)
        self.assertEqual([o.transmit for o in t._placed],
                         [False, False, True])

    def test_an_ambiguous_account_refuses_before_any_leg_is_placed(self):
        t = _connected(_trader())
        t._ib.managedAccounts.return_value = ["DU111", "DU222"]
        out = self._order(t, _fake_ib_module(),
                          stop_loss=95.0, take_profit=110.0)
        self.assertEqual(out["status"], "REJECTED")
        self.assertEqual(len(t._placed), 0)


class ProtectiveLevelSanityTests(TestCase):
    def _bracket(self, action, sl, tp, symbol="AAPL"):
        t = _connected(_trader(account_id="DU111"))
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            return t._bracket_orders(action, 10, symbol, sl, tp,
                                     min_tick=0.01)

    def test_a_stop_on_the_wrong_side_is_refused(self):
        """A stop above the target on a long is not protection — it is an
        instant exit at the worst price on the sheet."""
        self.assertIsNone(self._bracket("BUY", 110.0, 95.0))
        self.assertIsNone(self._bracket("SELL", 95.0, 110.0))

    def test_a_nonsense_level_is_refused_rather_than_sent(self):
        self.assertIsNone(self._bracket("BUY", 0, 110.0))
        self.assertIsNone(self._bracket("BUY", "not-a-price", 110.0))

    def test_prices_snap_to_the_contracts_real_tick(self):
        """Guessing decimals was wrong for everything but US equities:
        IDEALPRO forex ticks 0.00005, ES ticks 0.25. A price off the tick
        is rejected with error 110 — and a rejected stop is a naked
        position that still LOOKS protected."""
        from bot_program.engine.ibkr_client import IBKRTrader
        snap = IBKRTrader._snap_to_tick
        # ES: 4001.63 is not a multiple of 0.25.
        self.assertEqual(snap(4001.63, 0.25, widen=True), 4001.50)
        self.assertEqual(snap(4001.63, 0.25, widen=False), 4001.75)
        # EURUSD at a half-pip tick.
        self.assertEqual(snap(1.234567, 0.00005, widen=True), 1.23455)

    def test_a_snap_never_tightens_a_stop(self):
        """Rounding a long's stop UP would move it closer to the entry —
        the snap must only ever give the position more room."""
        from bot_program.engine.ibkr_client import IBKRTrader
        snap = IBKRTrader._snap_to_tick
        self.assertLessEqual(snap(95.007, 0.01, widen=True), 95.007)
        self.assertGreaterEqual(snap(95.003, 0.01, widen=False), 95.003)

    def test_an_unknown_tick_refuses_the_bracket(self):
        """Better an unprotected entry the bot still manages than legs
        TWS will reject while the row claims protection."""
        from bot_program.engine.ibkr_client import IBKRTrader
        self.assertIsNone(IBKRTrader._snap_to_tick(95.0, 0.0, widen=True))
        t = _connected(_trader(account_id="DU111"))
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            self.assertIsNone(t._bracket_orders("BUY", 10, "AAPL",
                                                95.0, 110.0, min_tick=0.0))


class ProtectionIsProvenNotAssumedTests(TestCase):
    """`protectedOnFill` turns bot-side stop management OFF. Claiming it
    for a leg the broker refused leaves the position naked AND unwatched
    — strictly worse than never bracketing."""

    def _order(self, t, mod, **kw):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", mod), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract", return_value=MagicMock()):
            return t.market_order("AAPL", "BUY", 10, **kw)

    def test_a_refused_stop_leg_forfeits_the_protection_claim(self):
        t = _connected(_trader(account_id="DU111"))
        real_place = t._ib.placeOrder.side_effect

        def _place(contract, order):
            placed = real_place(contract, order)
            # TWS refuses the last leg (error 110 off-tick, 201 margin…).
            if getattr(order, "orderType", "") == "STP":
                placed.orderStatus.status = "Cancelled"
            return placed

        t._ib.placeOrder.side_effect = _place
        out = self._order(t, _fake_ib_module(),
                          stop_loss=95.0, take_profit=110.0)
        self.assertNotIn("protectedOnFill", out)
        # And the accepted sibling is pulled back rather than left to
        # rest as an order nothing in the platform knows about.
        self.assertTrue(t._ib.cancelOrder.called)

    def test_a_partial_fill_forfeits_it_too(self):
        """Legs sized for 10 against a fill of 4 do not protect — the
        stop closes 4 and OPENS 6 the other way."""
        t = _connected(_trader(account_id="DU111"))
        real_place = t._ib.placeOrder.side_effect

        def _place(contract, order):
            placed = real_place(contract, order)
            if len(t._placed) == 1:
                placed.orderStatus.filled = 4      # parent partially filled
            return placed

        t._ib.placeOrder.side_effect = _place
        out = self._order(t, _fake_ib_module(),
                          stop_loss=95.0, take_profit=110.0)
        self.assertNotIn("protectedOnFill", out)
        self.assertTrue(t._ib.cancelOrder.called)

    def test_a_clean_bracket_still_claims_it(self):
        t = _connected(_trader(account_id="DU111"))
        out = self._order(t, _fake_ib_module(),
                          stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out["protectedOnFill"])
        self.assertFalse(t._ib.cancelOrder.called)


class FallbackLinkageTests(TestCase):
    """A child carrying parentId=0 is not a child: TWS holds the
    untransmitted parent forever and releases the STOP alone, which then
    OPENS a position against a book that never got the entry."""

    def test_the_hand_built_children_point_at_a_real_parent(self):
        t = _connected(_trader(account_id="DU111"), bracket_capable=False)
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()), \
                patch.object(t, "_connect", return_value=True), \
                patch.object(t, "_build_contract", return_value=MagicMock()):
            t.market_order("AAPL", "BUY", 10, stop_loss=95.0,
                           take_profit=110.0)
        parent, tp, sl = t._placed
        self.assertTrue(parent.orderId)
        self.assertEqual(tp.parentId, parent.orderId)
        self.assertEqual(sl.parentId, parent.orderId)
        # And the pair must cancel each other when either fills.
        self.assertEqual(tp.ocaGroup, sl.ocaGroup)

    def test_no_order_id_means_no_bracket_at_all(self):
        """Rather than emit orphan legs — an unprotected entry the bot
        still manages is far safer than a stop nobody owns."""
        t = _connected(_trader(account_id="DU111"), bracket_capable=False)
        t._ib.client = SimpleNamespace(
            getReqId=MagicMock(side_effect=RuntimeError("no id yet")))
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            self.assertIsNone(t._bracket_orders("BUY", 10, "AAPL", 95.0,
                                                110.0, min_tick=0.01))


class RefusedCloseTravelsTheFailurePathTests(TestCase):
    """The IBKR client never raises on a refusal — it RETURNS one. The
    engine inferred success from the absence of an exception and stripped
    the bracket off a position that was still live."""

    def test_a_rejected_close_raises_inside_the_engine(self):
        from pathlib import Path

        from django.conf import settings
        engine = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                  / "base.py").read_text(encoding="utf-8")
        self.assertIn("CLOSE_REFUSED_STATUSES", engine)
        self.assertIn("_submit_close_or_raise", engine)
        self.assertNotIn("close_result = self._submit_close_order(", engine)


class CancelOrderTests(TestCase):
    """The other half. The engine reaches for cancel_order BY NAME and
    skips cancellation entirely when it is missing, so brackets without
    it would leave a stop resting after a flatten."""

    def test_the_engine_can_find_it(self):
        from bot_program.engine.ibkr_client import IBKRTrader
        self.assertTrue(callable(getattr(IBKRTrader, "cancel_order", None)))

    def test_a_resting_leg_is_cancelled(self):
        t = _trader(account_id="DU111")
        t._ib = MagicMock()
        leg = _FakeOrder(orderId=77)
        t._ib.openTrades.return_value = [SimpleNamespace(order=leg)]
        with patch.object(t, "_connect", return_value=True):
            self.assertTrue(t.cancel_order("77"))
        t._ib.cancelOrder.assert_called_once_with(leg)

    def test_an_order_already_gone_is_not_an_error(self):
        """Filled or cancelled, the leg is no longer resting either way."""
        t = _trader(account_id="DU111")
        t._ib = MagicMock()
        t._ib.openTrades.return_value = []
        with patch.object(t, "_connect", return_value=True):
            self.assertFalse(t.cancel_order("77"))
        t._ib.cancelOrder.assert_not_called()

    def test_an_unreachable_session_is_loud_not_tidy(self):
        """"Could not reach the broker" is NOT "already gone". The
        flatten path books the row CLOSED on a tidy False, leaving a stop
        resting that later opens a position against a flat book."""
        t = _trader(account_id="DU111")
        with patch.object(t, "_connect", return_value=False):
            with self.assertRaises(ConnectionError):
                t.cancel_order("77")

    def test_the_engine_records_a_cancel_it_could_not_confirm(self):
        """And the engine must not swallow it: the row says so."""
        from pathlib import Path

        from django.conf import settings
        engine = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                  / "base.py").read_text(encoding="utf-8")
        self.assertIn("protective_legs_unconfirmed", engine)
        self.assertIn("not be confirmed cancelled", engine)


class TheEngineHonoursTheProtectionTests(TestCase):
    """Source pins: the two keys the client now returns are the two the
    engine already reads."""

    def test_protected_trades_skip_bot_side_management(self):
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
        engine = (base / "base.py").read_text(encoding="utf-8")
        self.assertIn('res.get("protectiveOrders")', engine)
        self.assertIn('res.get("protectedOnFill")', engine)
        self.assertIn('entry_meta["protected"] = True', engine)
        self.assertIn('_cancel_protective_orders', engine)
