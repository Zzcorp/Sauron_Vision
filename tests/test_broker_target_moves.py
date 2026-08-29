"""A broker-held TARGET can be moved, and only by a mover that means it.

Stage one refused the edit, which was the honest answer while no client
could move a target: raising one wrote the row, returned ok=true, recorded
an "in-place" broker modification that never happened, and left the
broker's limit resting where it was — so the position was taken out at the
old level.

Stage two is the capability. Each venue gets a `modify_target` that is a
SIBLING of `modify_protective`, not a flag on it, and each refuses the
other's leg type. That refusal is the safety property: every caller of
`modify_protective` is moving a stop, and the id list it walks holds the
take-profit too, so a mover that could be talked into either would put back
the exact bug the split exists to prevent.

Clearing a target is still refused. Cancelling a dependent order is a
different call from replacing one on every venue here, and a
half-implemented clear is the worst outcome available: the row would show
no target while the broker's still fills.

Run with:  python manage.py test tests.test_broker_target_moves
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = str(payload)
    r.raise_for_status.return_value = None
    return r


class AlpacaMovesItsLimitLegTests(SimpleTestCase):

    def _trader(self, leg_type, patch_status=200):
        from bot_program.engine.alpaca_client import AlpacaTrader
        c = AlpacaTrader("k", "s")
        sess = MagicMock()
        sess.get.return_value = _resp({"type": leg_type})
        sess.patch.return_value = _resp({}, patch_status)
        c._session = sess
        return c, sess

    def test_a_limit_leg_moves(self):
        c, sess = self._trader("limit")
        res = c.modify_target("tp1", 220.0)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(sess.patch.call_args.kwargs["json"],
                         {"limit_price": "220.0"})

    def test_a_stop_leg_is_refused(self):
        """A stop moved to a target price is a stop that fires at once."""
        c, sess = self._trader("stop")
        res = c.modify_target("sl1", 220.0)
        self.assertFalse(res["ok"])
        self.assertIn("not a take-profit", res["reason"])
        self.assertFalse(sess.patch.called)

    def test_a_stop_limit_leg_is_refused_too(self):
        """`stop_limit` contains "limit", so matching on that word alone
        would hand the target mover a stop."""
        c, sess = self._trader("stop_limit")
        self.assertFalse(c.modify_target("x", 220.0)["ok"])
        self.assertFalse(sess.patch.called)

    def test_a_leg_that_is_gone_is_an_answer_not_an_error(self):
        from bot_program.engine.alpaca_client import AlpacaTrader
        c = AlpacaTrader("k", "s")
        sess = MagicMock()
        sess.get.return_value = _resp({}, 404)
        c._session = sess
        res = c.modify_target("tp1", 220.0)
        self.assertFalse(res["ok"])
        self.assertIn("gone", res["reason"])

    def test_a_refusal_from_the_venue_is_reported(self):
        c, _ = self._trader("limit", patch_status=422)
        self.assertFalse(c.modify_target("tp1", 220.0)["ok"])


class OandaReplacesTheTradesTakeProfitTests(SimpleTestCase):

    def _trader(self, status=200):
        from bot_program.engine.oanda_client import OANDATrader
        c = OANDATrader("k", "101-1")
        sess = MagicMock()
        sess.get.return_value = _resp(
            {"trade": {"instrument": "EUR_USD"}})
        sess.put.return_value = _resp({}, status)
        c._session = sess
        return c, sess

    def test_the_target_is_sent_at_the_instruments_precision(self):
        c, sess = self._trader()
        res = c.modify_target("9001", 1.09876543)
        self.assertTrue(res["ok"], res.get("reason"))
        body = sess.put.call_args.kwargs["json"]
        self.assertEqual(body["takeProfit"]["price"], "1.09877")

    def test_a_jpy_cross_uses_three_digits(self):
        from bot_program.engine.oanda_client import OANDATrader
        c = OANDATrader("k", "101-1")
        sess = MagicMock()
        sess.get.return_value = _resp({"trade": {"instrument": "USD_JPY"}})
        sess.put.return_value = _resp({})
        c._session = sess
        c.modify_target("9001", 151.23456)
        self.assertEqual(
            sess.put.call_args.kwargs["json"]["takeProfit"]["price"],
            "151.235")

    def test_only_the_take_profit_is_sent(self):
        """The stop path sends only `stopLoss` and does not disturb the
        target; the symmetric call must not disturb the stop."""
        c, sess = self._trader()
        c.modify_target("9001", 1.1)
        self.assertEqual(list(sess.put.call_args.kwargs["json"]),
                         ["takeProfit"])

    def test_a_refusal_is_not_a_success(self):
        c, _ = self._trader(status=400)
        self.assertFalse(c.modify_target("9001", 1.1)["ok"])


class IbkrMovesTheNamedTargetTests(SimpleTestCase):

    def _leg(self, oid=2, kind="LMT", action="SELL", price=115.0):
        return SimpleNamespace(orderId=oid, action=action, orderType=kind,
                               lmtPrice=price, auxPrice=95.0,
                               account="DU111")

    def _trader(self, *legs, min_tick=0.05, status="Submitted"):
        from bot_program.engine.ibkr_client import IBKRTrader
        t = IBKRTrader(timeout=0.1, account_id="DU111")
        t._connected = True
        t._ib = MagicMock()
        t._ib.isConnected.return_value = True
        t._ib.managedAccounts.return_value = ["DU111"]
        t._ib.reqContractDetails.return_value = [
            SimpleNamespace(minTick=min_tick)]
        t._ib.openTrades.return_value = [
            SimpleNamespace(order=o, contract=SimpleNamespace(symbol="AAPL"))
            for o in legs]
        t._ib.placeOrder.side_effect = lambda c, o: SimpleNamespace(
            order=o, orderStatus=SimpleNamespace(status=status, filled=0),
            log=[])
        return t

    def test_a_long_target_rounds_up_away_from_the_position(self):
        """Away, so the level quoted is one the venue will actually give."""
        leg = self._leg(action="SELL")
        t = self._trader(leg)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_target("2", 220.03)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["price"], 220.05)
        self.assertEqual(leg.lmtPrice, 220.05)

    def test_a_short_target_rounds_down(self):
        leg = self._leg(action="BUY")
        t = self._trader(leg)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_target("2", 220.03)
        self.assertEqual(res["price"], 220.00)

    def test_a_stop_leg_is_refused(self):
        leg = self._leg(kind="STP")
        t = self._trader(leg)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_target("2", 220.0)
        self.assertFalse(res["ok"])
        self.assertIn("not a take-profit", res["reason"])
        self.assertFalse(t._ib.placeOrder.called)

    def test_a_rejected_modification_is_not_reported_as_moved(self):
        t = self._trader(self._leg(), status="Cancelled")
        with patch.object(t, "_connect", return_value=True):
            self.assertFalse(t.modify_target("2", 220.0)["ok"])

    def test_an_unreadable_tick_is_refused(self):
        leg = self._leg()
        t = self._trader(leg, min_tick=0)
        with patch.object(t, "_connect", return_value=True):
            res = t.modify_target("2", 220.0)
        self.assertFalse(res["ok"])
        self.assertEqual(leg.lmtPrice, 115.0)


class TheOperatorEditReachesTheBrokerTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("tgt_u", password="x")
        from bot_program.models import AssetBotConfig
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="T", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)

    def _trade(self, **meta):
        from bot_program.models import AssetBotTrade
        base = {"protected": True, "protective_order_ids": ["2", "3"]}
        base.update(meta)
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
            status="OPEN", paper=False, opened_at=timezone.now(),
            metadata=base)

    def _client(self, target_ok=True, stop_ok=True):
        c = MagicMock()
        c.modify_target.return_value = {
            "ok": target_ok, "price": 120.0,
            "reason": "" if target_ok else "venue refused"}
        c.modify_protective.return_value = {
            "ok": stop_ok, "price": 97.0,
            "reason": "" if stop_ok else "venue refused"}
        return c

    def _adjust(self, trade, client, **kw):
        from bot_program.adjust_levels import adjust_levels
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return adjust_levels(self.user, trade, **kw)

    def test_raising_a_target_now_reaches_the_broker(self):
        from bot_program.models import AssetBotTrade
        t = self._trade(protective_target_id="2")
        client = self._client()
        res = self._adjust(t, client, target=Decimal("120"))
        self.assertTrue(res["ok"], res.get("error"))
        client.modify_target.assert_called_once()
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("120"))

    def test_the_named_target_handle_is_preferred_over_the_flat_list(self):
        t = self._trade(protective_target_id="2")
        client = self._client()
        self._adjust(t, client, target=Decimal("120"))
        self.assertEqual(client.modify_target.call_args[0][0], "2")

    def test_a_venue_refusal_leaves_the_row_alone(self):
        from bot_program.models import AssetBotTrade
        t = self._trade(protective_target_id="2")
        res = self._adjust(t, self._client(target_ok=False),
                           target=Decimal("120"))
        self.assertFalse(res["ok"])
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("110"))

    def test_a_half_applied_edit_says_which_half_landed(self):
        """The target moved at the venue and the stop did not. Saying
        "nothing was changed" here would be a lie the operator acts on."""
        t = self._trade(protective_target_id="2", protective_stop_id="3")
        res = self._adjust(t, self._client(stop_ok=False),
                           target=Decimal("120"), stop=Decimal("97"))
        self.assertFalse(res["ok"])
        self.assertIn("target WAS moved", res["error"])

    def test_clearing_a_broker_held_target_is_still_refused(self):
        from bot_program.models import AssetBotTrade
        t = self._trade(protective_target_id="2")
        res = self._adjust(t, self._client(), clear_target=True)
        self.assertFalse(res["ok"])
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("110"))

    def test_a_client_with_no_target_mover_is_named_not_faked(self):
        from bot_program.models import AssetBotTrade
        t = self._trade(protective_target_id="2")
        client = MagicMock(spec=["modify_protective"])
        res = self._adjust(t, client, target=Decimal("120"))
        self.assertFalse(res["ok"])
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("110"))
