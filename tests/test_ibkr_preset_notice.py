"""A notice is not a rejection, and a stamp is not a fact.

On 2026-09-07 at 15:13 UTC — a Monday, the US session open — the first
real order this deployment ever sent came back:

    broker_rejected: Error 10349, reqId 11: Order TIF was set to DAY
    based on order preset.

Nothing opened, nothing rested, nothing executed. Three defects met on
that one order, and each is pinned here:

1. ib_insync 0.9.86 knows eight warning codes; every other code that
   arrives with an order's reqId is FATAL to it — the trade is marked
   Cancelled in memory (the broker cancels nothing), and because it now
   counts as done, every later error on that order is dropped from its
   log. 10349 is TWS commenting on an order it has accepted. The shield
   keeps such orders alive and lets every other code through untouched.

2. `_dead_order_reason` joined every log line, so the one readable line
   was presented as the cause. A notice is not a reason; a child's
   refusal often is; and when nothing says anything, the string says
   that, and where to look.

3. The entry's tif was EMPTY — "whatever the account preset says" — and
   the protective legs were STAMPED GTC and never read back. A preset
   that rewrites API orders turns a GTC stop into a DAY stop that dies at
   the close while the row says `protected`: the naked overnight
   position commit 9e2bc10 exists to prevent, back through one account
   setting. The entry now says DAY out loud, and the legs' accepted tif is
   read back from TWS before anything is claimed for them.

Run with:  python manage.py test tests.test_ibkr_preset_notice
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

NOTICE = "Order TIF was set to DAY based on order preset."


def _trader(**kw):
    from bot_program.engine.ibkr_client import IBKRTrader
    return IBKRTrader(timeout=0.1, **kw)


class _FakeOrder(SimpleNamespace):
    """An ib_insync Order stands in as a plain attribute bag."""


def _entry(message="", code=0, status="Submitted"):
    return SimpleNamespace(time=None, status=status, message=message,
                           errorCode=code)


def _fake_ib_module():
    """A stand-in for the ib_insync module the client imports as _ib."""
    mod = MagicMock()
    mod.MarketOrder.side_effect = lambda a, q: _FakeOrder(
        action=a, totalQuantity=q, orderType="MKT", transmit=True, orderId=0)
    mod.LimitOrder.side_effect = lambda a, q, p: _FakeOrder(
        action=a, totalQuantity=q, lmtPrice=p, orderType="LMT",
        transmit=True, orderId=0)
    mod.StopOrder.side_effect = lambda a, q, p: _FakeOrder(
        action=a, totalQuantity=q, auxPrice=p, orderType="STP",
        transmit=True, orderId=0)
    mod.TradeLogEntry.side_effect = lambda t, s, m, c: _entry(m, c, s)
    return mod


def _connected(t, *, bracket_capable=True, parent_status="Filled",
               open_orders=None, open_orders_raise=False):
    """A live session: parent id 1, target id 2, stop id 3.

    `open_orders` is what reqOpenOrders() reports back — the broker's own
    view of the legs, tif included. None means "report the legs as GTC",
    i.e. the honest broker with no preset in the way.
    """
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.managedAccounts.return_value = ["DU111"]

    def _bracket(action, qty, limitPrice=None, takeProfitPrice=None,
                 stopLossPrice=None):
        if not bracket_capable:
            raise AttributeError("no bracketOrder in this build")
        exit_ = "SELL" if action == "BUY" else "BUY"
        return [_FakeOrder(action=action, totalQuantity=qty, orderType="LMT",
                           transmit=True, orderId=1),
                _FakeOrder(action=exit_, totalQuantity=qty,
                           lmtPrice=takeProfitPrice, orderType="LMT",
                           transmit=True, orderId=2),
                _FakeOrder(action=exit_, totalQuantity=qty,
                           auxPrice=stopLossPrice, orderType="STP",
                           transmit=True, orderId=3)]

    t._ib.bracketOrder.side_effect = _bracket
    t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
    t._ib.client = SimpleNamespace(getReqId=lambda: 1)
    placed = []

    def _place(contract, order):
        placed.append(order)
        order.orderId = getattr(order, "orderId", 0) or len(placed)
        first = len(placed) == 1
        status = parent_status if first else "Submitted"
        filled = order.totalQuantity if (first and status == "Filled") else 0
        return SimpleNamespace(
            order=order,
            orderStatus=SimpleNamespace(status=status, filled=filled,
                                        avgFillPrice=100.0 if filled else 0),
            log=[])

    t._ib.placeOrder.side_effect = _place
    t._placed = placed
    if open_orders_raise:
        t._ib.reqOpenOrders.side_effect = RuntimeError("socket gone")
    else:
        t._ib.reqOpenOrders.return_value = (
            [SimpleNamespace(orderId=2, tif="GTC"),
             SimpleNamespace(orderId=3, tif="GTC")]
            if open_orders is None else open_orders)
    return t


def _order(t, mod, **kw):
    from bot_program.engine import ibkr_client
    with patch.object(ibkr_client, "_ib", mod), \
            patch.object(t, "_connect", return_value=True), \
            patch.object(t, "_build_contract", return_value=MagicMock()):
        return t.market_order("GLDM", "BUY", 10, **kw)


def _cancelled_ids(t):
    return sorted(getattr(c.args[0], "orderId", None)
                  for c in t._ib.cancelOrder.call_args_list)


# ── 1. the shield ───────────────────────────────────────────────────────────

class _FakeWrapper:
    """Just enough of ib_insync.wrapper.Wrapper for the shield to wrap."""

    def __init__(self, trade):
        self.clientId = 7
        self.lastTime = None
        self.trades = {(7, 11): trade}
        self._reqId2Contract = {11: "GLDM-contract"}
        self.original = MagicMock(name="Wrapper.error")
        self.error = self.original


def _live_trade(status="PreSubmitted"):
    return SimpleNamespace(order=SimpleNamespace(orderId=11),
                           orderStatus=SimpleNamespace(status=status),
                           log=[])


class TheShieldTests(SimpleTestCase):

    def _shielded(self):
        from bot_program.engine import ibkr_client
        trade = _live_trade()
        wrapper = _FakeWrapper(trade)
        ib = SimpleNamespace(wrapper=wrapper, errorEvent=MagicMock())
        t = _trader()
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            t._shield_orders_from_notices(ib)
            return ib, wrapper, trade

    def test_a_notice_leaves_the_order_alive(self):
        """The whole defect: the library would have marked it Cancelled."""
        ib, wrapper, trade = self._shielded()
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            wrapper.error(11, 10349, NOTICE, "")
        self.assertEqual(trade.orderStatus.status, "PreSubmitted")
        wrapper.original.assert_not_called()

    def test_the_notice_is_recorded_without_a_code(self):
        """Visible on the trade for anyone reading it, and NOT an error:
        `_leg_is_resting` reads a non-zero errorCode as a refusal."""
        ib, wrapper, trade = self._shielded()
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            wrapper.error(11, 10349, NOTICE, "")
        self.assertEqual(len(trade.log), 1)
        self.assertIn("Notice 10349, reqId 11", trade.log[0].message)
        self.assertEqual(trade.log[0].errorCode, 0)

    def test_listeners_still_hear_it(self):
        ib, wrapper, trade = self._shielded()
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            wrapper.error(11, 10349, NOTICE, "")
        ib.errorEvent.emit.assert_called_once_with(
            11, 10349, NOTICE, "GLDM-contract")

    def test_a_real_error_passes_straight_through(self):
        """Nothing else about the library's handling changes."""
        ib, wrapper, trade = self._shielded()
        wrapper.error(11, 201, "Order rejected - reason: margin", "")
        wrapper.original.assert_called_once_with(
            11, 201, "Order rejected - reason: margin", "")
        self.assertEqual(trade.log, [])

    def test_a_notice_for_an_unknown_reqid_is_harmless(self):
        ib, wrapper, trade = self._shielded()
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            wrapper.error(99, 10349, NOTICE, "")
        self.assertEqual(trade.log, [])
        wrapper.original.assert_not_called()

    def test_installed_once_per_session(self):
        """A reconnect must not stack a second layer on the first."""
        ib, wrapper, trade = self._shielded()
        first = wrapper.error
        _trader()._shield_orders_from_notices(ib)
        self.assertIs(wrapper.error, first)

    def test_connect_installs_it(self):
        """The one place every live session passes through."""
        from bot_program.engine import ibkr_client
        wrapper = _FakeWrapper(_live_trade())
        session = MagicMock()
        session.wrapper = wrapper
        mod = _fake_ib_module()
        mod.IB.return_value = session
        t = _trader()
        with patch.object(ibkr_client, "_ib", mod), \
                patch.object(ibkr_client, "is_ibkr_available",
                             return_value=True):
            self.assertTrue(t._connect())
        self.assertTrue(getattr(wrapper, "_sv_notice_shield", False))
        self.assertIsNot(wrapper.error, wrapper.original)


class WhatCountsAsANoticeTests(SimpleTestCase):

    def _is(self, code, text):
        from bot_program.engine.ibkr_client import IBKRTrader
        return IBKRTrader._is_order_notice(code, text)

    def test_the_code_alone(self):
        self.assertTrue(self._is(10349, ""))

    def test_the_sentence_alone_catches_a_sibling_preset(self):
        """IBKR spells every preset substitution the same way; the next
        one (outsideRth, a price cap) must not need a code we have not
        seen yet to stay a comment."""
        self.assertTrue(self._is(
            0, "Order outsideRth was set to true based on order preset."))

    def test_the_shields_own_entries(self):
        self.assertTrue(self._is(0, "Notice 10349, reqId 11: " + NOTICE))

    def test_a_rejection_is_not_one(self):
        self.assertFalse(self._is(201, "Order rejected - reason: margin"))
        self.assertFalse(self._is(10318, "This order doesn't support "
                                         "fractional quantity trading"))

    def test_garbage_codes_do_not_raise(self):
        self.assertFalse(self._is("x", None))


# ── 2. the reason ───────────────────────────────────────────────────────────

def _dead(order_id=11, log=(), status="Cancelled"):
    return SimpleNamespace(order=SimpleNamespace(orderId=order_id),
                           orderStatus=SimpleNamespace(status=status,
                                                       filled=0),
                           log=list(log))


class TheReasonTests(SimpleTestCase):

    def _why(self, trade, children=()):
        from bot_program.engine.ibkr_client import IBKRTrader
        return IBKRTrader._dead_order_reason(trade, 0, children)

    def test_a_notice_is_never_presented_as_the_cause(self):
        """The exact string the operator was shown on 2026-09-07."""
        why = self._why(_dead(log=[
            _entry(),
            _entry("Error 10349, reqId 11: " + NOTICE, 10349)]))
        self.assertTrue(why.startswith("broker_rejected: "))
        self.assertNotIn("preset", why)

    def test_silence_says_it_is_silence_and_where_to_look(self):
        why = self._why(_dead(log=[_entry("Notice 10349, reqId 11: x", 0)]))
        self.assertIn("no message on this order", why)
        self.assertIn("reqId 11", why)
        self.assertIn("Cancelled", why)

    def test_a_childs_refusal_is_the_answer_when_the_parent_is_mute(self):
        """A stop TWS will not take kills the whole bracket; the message
        lands on the leg's reqId, never the parent's."""
        stop = _dead(order_id=13, log=[
            _entry("Error 10318, reqId 13: no fractional stops", 10318)])
        why = self._why(_dead(), children=[stop])
        self.assertIn("leg 13: Error 10318", why)
        self.assertNotIn("no message", why)

    def test_the_parents_own_error_still_wins(self):
        stop = _dead(order_id=13, log=[_entry("leg noise", 1)])
        why = self._why(_dead(log=[_entry("Error 201, reqId 11: margin",
                                          201)]),
                        children=[stop])
        self.assertIn("Error 201", why)
        self.assertNotIn("leg 13", why)

    def test_alive_is_none(self):
        self.assertIsNone(self._why(_dead(status="Submitted")))

    def test_inactive_counts_as_dead(self):
        self.assertIn("Inactive", self._why(_dead(status="Inactive")))

    def test_the_old_two_argument_call_still_works(self):
        """Three other call sites pass no children."""
        from bot_program.engine.ibkr_client import IBKRTrader
        self.assertIsNotNone(IBKRTrader._dead_order_reason(_dead(), 0))


class ALegWithANoticeStillRestsTests(SimpleTestCase):
    """`_leg_is_resting` read ANY errorCode on the log as a refusal — so a
    10349 entry written by a library that does not shield would have had
    the bracket cancelled and the position handed to bot-side management
    over a comment."""

    def _resting(self, log):
        from bot_program.engine.ibkr_client import IBKRTrader
        return IBKRTrader._leg_is_resting(SimpleNamespace(
            orderStatus=SimpleNamespace(status="Submitted"), log=log))

    def test_a_notice_entry_is_not_a_refusal(self):
        self.assertTrue(self._resting([_entry(NOTICE, 10349)]))

    def test_a_real_error_entry_still_is(self):
        self.assertFalse(self._resting([_entry("margin", 201)]))


# ── 3. the entry's tif, said out loud ───────────────────────────────────────

class TheEntrySaysItsTifTests(SimpleTestCase):

    def _bracket(self, t):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_ib", _fake_ib_module()):
            return t._bracket_orders("BUY", 10, "GLDM", 95.0, 110.0,
                                     min_tick=0.01)

    def test_the_helper_built_parent_is_day_and_the_legs_gtc(self):
        orders = self._bracket(_connected(_trader(account_id="DU111")))
        self.assertEqual(orders[0].tif, "DAY")
        self.assertEqual([o.tif for o in orders[1:]], ["GTC", "GTC"])

    def test_the_hand_built_parent_too(self):
        t = _connected(_trader(account_id="DU111"), bracket_capable=False)
        orders = self._bracket(t)
        self.assertEqual(orders[0].tif, "DAY")
        self.assertEqual([o.tif for o in orders[1:]], ["GTC", "GTC"])

    def test_an_unprotected_entry_says_it_too(self):
        t = _connected(_trader(account_id="DU111"))
        _order(t, _fake_ib_module())
        self.assertEqual(len(t._placed), 1)
        self.assertEqual(t._placed[0].tif, "DAY")

    def test_an_option_entry_says_it_too(self):
        from bot_program.engine import ibkr_client
        t = _connected(_trader(account_id="DU111"))
        with patch.object(ibkr_client, "_ib", _fake_ib_module()), \
                patch.object(t, "_connect", return_value=True):
            t.market_order_option("AAPL", 200.0, "2026-12-18", "C",
                                  "BUY", 1)
        self.assertEqual(t._placed[0].tif, "DAY")

    def test_the_constants(self):
        from bot_program.engine.ibkr_client import IBKRTrader
        self.assertEqual(IBKRTrader.ENTRY_TIF, "DAY")
        self.assertEqual(IBKRTrader.PROTECTIVE_LEG_TIF, "GTC")
        self.assertIn(10349, IBKRTrader.ORDER_NOTICE_CODES)


# ── 4. the accepted tif, read back ──────────────────────────────────────────

class TheStampIsReadBackTests(SimpleTestCase):

    def test_an_honest_broker_keeps_the_bracket(self):
        t = _connected(_trader(account_id="DU111"))
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out.get("protectedOnFill"))
        self.assertEqual(_cancelled_ids(t), [])
        t._ib.reqOpenOrders.assert_called_once()

    def test_a_day_stop_is_not_protection(self):
        """The preset case. The legs come down; the row is never told it
        is protected by a stop that dies at 20:00 UTC."""
        t = _connected(_trader(account_id="DU111"), open_orders=[
            SimpleNamespace(orderId=2, tif="DAY"),
            SimpleNamespace(orderId=3, tif="DAY")])
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertNotIn("protectedOnFill", out)
        self.assertNotIn("protectiveOrders", out)
        self.assertEqual(_cancelled_ids(t), [2, 3])

    def test_the_note_names_the_cause_and_the_fix(self):
        t = _connected(_trader(account_id="DU111"), open_orders=[
            SimpleNamespace(orderId=3, tif="DAY")])
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        note = out["protectionNote"]
        self.assertIn("leg 3 is DAY", note)
        self.assertIn("preset", note)
        self.assertIn("GTC", note)
        self.assertIn("bot-side management", note)

    def test_the_parent_is_not_cancelled_for_it(self):
        """It filled. Cancelling a filled parent is noise at best."""
        t = _connected(_trader(account_id="DU111"), open_orders=[
            SimpleNamespace(orderId=3, tif="DAY")])
        _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertNotIn(1, _cancelled_ids(t))

    def test_only_the_stop_decides(self):
        """A DAY target beside a GTC stop leaves the position protected —
        a target is just an order."""
        t = _connected(_trader(account_id="DU111"), open_orders=[
            SimpleNamespace(orderId=2, tif="DAY"),
            SimpleNamespace(orderId=3, tif="GTC")])
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out.get("protectedOnFill"))
        self.assertEqual(_cancelled_ids(t), [])

    def test_could_not_look_is_not_a_downgrade(self):
        """A dead read must not strip a good stop; the vanished-stop check
        watches the legs from the next tick on."""
        t = _connected(_trader(account_id="DU111"), open_orders_raise=True)
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out.get("protectedOnFill"))
        self.assertEqual(_cancelled_ids(t), [])

    def test_legs_absent_from_the_report_are_left_to_the_resting_check(self):
        t = _connected(_trader(account_id="DU111"), open_orders=[])
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out.get("protectedOnFill"))

    def test_an_unprotected_entry_never_asks(self):
        t = _connected(_trader(account_id="DU111"))
        _order(t, _fake_ib_module())
        t._ib.reqOpenOrders.assert_not_called()


class AWorkingEntryIsReadBackTooTests(SimpleTestCase):
    """A market order held for the open books a WORKING row whose legs arm
    on the fill. Legs the preset already turned into DAY are withdrawn now,
    not inherited as protection later."""

    def test_downgraded_legs_are_withdrawn_and_the_parent_keeps_working(self):
        t = _connected(_trader(account_id="DU111"), parent_status="Submitted",
                       open_orders=[SimpleNamespace(orderId=3, tif="DAY")])
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out.get("working"))
        self.assertNotIn("protectiveOrders", out)
        self.assertEqual(_cancelled_ids(t), [2, 3])
        self.assertIn("preset", out["protectionNote"])

    def test_gtc_legs_ride_along_as_before(self):
        t = _connected(_trader(account_id="DU111"), parent_status="Submitted")
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out.get("working"))
        self.assertEqual(len(out["protectiveOrders"]), 2)
        self.assertEqual(_cancelled_ids(t), [])


class TheRowKeepsTheNoteTests(SimpleTestCase):
    """Both consumers of the fill copy the note onto the row, so the
    operator reads why a live position is bot-managed on the row itself."""

    def _src(self, *parts):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR).joinpath(*parts)
                .read_text(encoding="utf-8"))

    def test_the_engine(self):
        src = self._src("bot_program", "asset_engine", "base.py")
        self.assertIn('note = res.get("protectionNote")', src)
        self.assertIn('entry_meta["protection_note"] = str(note)[:300]', src)

    def test_the_manual_lane(self):
        src = self._src("bot_program", "manual_trade.py")
        self.assertIn('note = res.get("protectionNote")', src)
        self.assertIn('extra["protection_note"] = str(note)[:300]', src)
