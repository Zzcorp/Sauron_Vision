"""The protective legs outlive the session, and a row stops claiming a
stop the broker no longer holds.

Two halves of one defect. ib_insync leaves Order.tif empty and TWS reads
empty as DAY, so every IBKR bracket's stop and target EXPIRED at the
session close — while the row kept `protected=True`, and protected rows
skip every bot-side SL/TP check. Every shipped default holds positions
for days: from the first close onward the position was naked and nothing
was watching. The legs are now GTC; and because a leg can still vanish
(cancelled at TWS, refused late, expired under an older build), the tick
asks the broker whether the stop still rests and, when it is gone while
the position is still held, un-protects the row and takes it back.

Run with:  python manage.py test tests.test_ibkr_gtc_and_vanished_legs
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


# ── fixtures shared with the bracket tests ─────────────────────────────────

def _trader(**kw):
    from bot_program.engine.ibkr_client import IBKRTrader
    return IBKRTrader(timeout=0.1, **kw)


class _FakeOrder(SimpleNamespace):
    """An ib_insync Order stands in as a plain attribute bag."""


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


def _connected(t, bracket_capable=True):
    t._connected = True
    t._ib = MagicMock()
    t._ib.isConnected.return_value = True
    t._ib.managedAccounts.return_value = ["DU111"]

    def _bracket(action, qty, limitPrice=None, takeProfitPrice=None,
                 stopLossPrice=None):
        if not bracket_capable:
            raise AttributeError("no bracketOrder in this build")
        exit_action = "SELL" if action == "BUY" else "BUY"
        return [
            _FakeOrder(action=action, totalQuantity=qty, orderType="LMT",
                       transmit=True, orderId=1),
            _FakeOrder(action=exit_action, totalQuantity=qty,
                       lmtPrice=takeProfitPrice, orderType="LMT",
                       transmit=True, orderId=2),
            _FakeOrder(action=exit_action, totalQuantity=qty,
                       auxPrice=stopLossPrice, orderType="STP",
                       transmit=True, orderId=3),
        ]

    t._ib.bracketOrder.side_effect = _bracket
    t._ib.reqContractDetails.return_value = [SimpleNamespace(minTick=0.01)]
    t._ib.client = SimpleNamespace(getReqId=lambda: 4242)
    placed = []

    def _place(contract, order):
        placed.append(order)
        order.orderId = getattr(order, "orderId", 0) or (100 + len(placed))
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


def _order(t, mod, **kw):
    from bot_program.engine import ibkr_client
    with patch.object(ibkr_client, "_ib", mod), \
            patch.object(t, "_connect", return_value=True), \
            patch.object(t, "_build_contract", return_value=MagicMock()):
        return t.market_order("AAPL", "BUY", 10, **kw)


# ═══ 1. The legs are good till cancelled ═══════════════════════════════════

class TheProtectionOutlivesTheSessionTests(TestCase):

    def test_bracket_children_are_gtc_and_the_parent_is_not(self):
        t = _connected(_trader(account_id="DU111"))
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out["protectedOnFill"])
        parent, target, stop = t._placed
        self.assertEqual(target.tif, "GTC")
        self.assertEqual(stop.tif, "GTC")
        self.assertNotEqual(getattr(parent, "tif", ""), "GTC")

    def test_hand_built_legs_are_gtc_too(self):
        t = _connected(_trader(account_id="DU111"), bracket_capable=False)
        out = _order(t, _fake_ib_module(), stop_loss=95.0, take_profit=110.0)
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual([getattr(o, "tif", "") for o in t._placed[1:]],
                         ["GTC", "GTC"])


# ═══ 2. What rests at the broker, in one read ══════════════════════════════

class RestingOrderIdsTests(SimpleTestCase):

    def _open(self, *rows):
        t = _trader()
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.openTrades.return_value = [
            SimpleNamespace(order=SimpleNamespace(orderId=oid),
                            orderStatus=SimpleNamespace(status=status))
            for oid, status in rows]
        return t

    def test_working_legs_are_listed(self):
        t = self._open((12, "Submitted"), (13, "PreSubmitted"))
        self.assertEqual(t.resting_order_ids(), {"12", "13"})

    def test_a_cancelled_leg_is_not_resting(self):
        t = self._open((12, "Submitted"), (13, "Cancelled"), (14, "Inactive"))
        self.assertEqual(t.resting_order_ids(), {"12"})

    def test_unreachable_is_none_never_empty(self):
        """'could not look' must never be read as 'gone'."""
        t = _trader()
        with patch.object(t, "_connect", return_value=False):
            self.assertIsNone(t.resting_order_ids())


# ═══ 3. The tick takes back a position whose stop is gone ══════════════════

def _user(name):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, name="VANISH"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode="live",
        symbols=["NVDA"], capital=Decimal("10000"), enabled=True)


def _trade(cfg, **meta):
    from bot_program.models import AssetBotTrade
    metadata = {"protected": True, "protective_order_ids": ["12", "13"],
                "protective_stop_id": "13"}
    metadata.update(meta)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="NVDA", side="BUY",
        qty=Decimal("5"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=False, metadata=metadata)


def _client(*, resting, positions, cancels=True):
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": "101", "symbol": "NVDA"}
    # EXPLICIT, not a MagicMock auto-attribute: left implicit, cancel_order
    # returns a truthy Mock and the "a leg that will not come down keeps the
    # row PROTECTED" arm below is never exercised in either direction.
    client.cancel_order.return_value = bool(cancels)
    if isinstance(resting, Exception):
        client.resting_order_ids.side_effect = resting
    else:
        client.resting_order_ids.return_value = resting
    if isinstance(positions, Exception):
        client.get_positions.side_effect = positions
    else:
        client.get_positions.return_value = positions
    return client


HELD = [{"symbol": "NVDA", "qty": 5.0, "side": "BUY", "sec_type": "STK"}]


class AVanishedStopUnprotectsTheRowTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("vanish_u")
        self.cfg = _cfg(self.user)

    def _tick(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(self.cfg).manage_positions()

    def _alerts(self):
        from alerts.models import Notification
        return Notification.objects.filter(user=self.user,
                                           title__icontains="unprotected")

    def test_stop_gone_and_position_held_flips_protected_off_and_alerts_once(self):
        trade = _trade(self.cfg)
        client = _client(resting={"12"}, positions=HELD)   # the stop, 13, is gone
        self._tick(client)
        trade.refresh_from_db()
        self.assertFalse(trade.metadata["protected"])
        self.assertIn("protection_vanished_at", trade.metadata)
        self.assertIn("13", trade.metadata["protection_vanished_reason"])
        # The target may still rest; the close path cancels whatever is listed.
        self.assertEqual(trade.metadata["protective_order_ids"], ["12", "13"])
        self.assertEqual(self._alerts().count(), 1)
        self._tick(client)                                   # next tick
        self.assertEqual(self._alerts().count(), 1)          # said once

    def test_the_surviving_target_is_cancelled_before_the_bot_takes_over(self):
        """Bot-side SL/TP runs off the same levels the resting leg sits at,
        and _close_trade goes to market BEFORE it strips legs — a target left
        armed beside a bot-side take-profit sells the position twice."""
        trade = _trade(self.cfg)
        client = _client(resting={"12"}, positions=HELD)   # 13 gone, 12 rests
        self._tick(client)
        trade.refresh_from_db()
        self.assertFalse(trade.metadata["protected"])
        client.cancel_order.assert_any_call("12")
        self.assertEqual(trade.metadata["protection_legs_cancelled"], ["12"])

    def test_a_leg_that_will_not_cancel_keeps_the_row_protected(self):
        """Refusing to un-protect is the safe direction: the broker keeps a
        position whose GTC leg the platform could not take down."""
        trade = _trade(self.cfg)
        client = _client(resting={"12"}, positions=HELD, cancels=False)
        self._tick(client)
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self.assertTrue(trade.metadata["protective_legs_unconfirmed"])
        self.assertEqual(self._alerts().count(), 1)

    def test_a_resting_stop_keeps_the_row_protected(self):
        trade = _trade(self.cfg)
        self._tick(_client(resting={"12", "13"}, positions=HELD))
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self.assertEqual(self._alerts().count(), 0)

    def test_a_position_the_broker_no_longer_holds_is_left_to_reconcile(self):
        """The stop FILLED: the row is closed by reconciliation, not taken
        back here for a second exit."""
        trade = _trade(self.cfg)
        self._tick(_client(resting=set(), positions=[]))
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self.assertEqual(self._alerts().count(), 0)

    def test_an_unreadable_broker_changes_nothing(self):
        trade = _trade(self.cfg)
        self._tick(_client(resting=None, positions=HELD))
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self._tick(_client(resting=set(), positions=RuntimeError("socket gone")))
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["protected"])
        self.assertEqual(self._alerts().count(), 0)

    def test_the_alert_is_operator_kind_so_a_muted_bot_feed_cannot_silence_it(self):
        from bot_program.notifications import BOT_KINDS, OPERATOR_KINDS
        self.assertIn("protection_vanished", OPERATOR_KINDS)
        self.assertNotIn("protection_vanished", BOT_KINDS)
