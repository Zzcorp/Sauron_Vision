"""THE REAL ACCOUNT, MEASURED (2026-09-26).

On 2026-09-26, ~21:25-22:03 UTC (a Saturday, code 097e72c), the operator
sent the platform's first real orders through the adapter, from a shell
client built env='live' (the eToro row stayed demo on /brokers/, no class
ticked):

  AAPL 0.04 BUY, market shut   accepted and HELD {11, WaitingForMarket},
                               order 1596774177, frozenAmount 14.64; then
                               WITHDRAWN at 22:03:11 UTC: DELETE
                               /api/v3/trading/execution/orders/1596774177
                               (no segment) -> 202 {"orderId":1596774177,
                               "referenceId":""}; 3 s later {7, Canceled};
                               used margin 31.47 -> 16.83.
  BTC 0.0002 BUY               FILLED at once: order 1596774178, position
                               3588477891, avgPrice 84145.8, settlementType
                               REAL at 1x, fees 0.17; the stop sent at
                               79934.97 HELD at 75745.8; CLOSED at 22:03:24
                               UTC by the v1 market-close POST (no segment,
                               attested until then by a GET answering 405):
                               orderForClose{orderID 1596736969, orderType
                               19, statusID 1}, the open order's state
                               "closed"; cells {2249.65, 0.0}.

What this module pins, each with the REAL EtoroTrader over a fake wire (no
HTTP call leaves the box):

  * the real DELETE URL, and cancel_order proving Canceled on a real
    client with the measured 202 body; a lookup whose status nobody can
    read, or one reading a CLOSE order (type 19), sends nothing;
  * the tick withdrawing a held LIVE entry after ENTRY_WORKING_MAX_HOURS
    exactly as it does on demo — the same words, no alert — and the kill
    switch the same;
  * the levered-working alert's words and the TAKE TRADE note: one promise
    on both worlds, the note RUN on a demo and a live client;
  * etoro_smoke's close and DELETE lines on a live row;
  * the crypto proof: "crypto" in ETORO_PROVEN (test_proof_crypto in
    tests/test_etoro_client.py), ETORO_PROVEN_LEVERAGE still empty — which
    binds the attack mode's chooser alone: a TYPED 2 on a crypto config
    clears every gate once etoro_leverage_live is ON;
  * broker_portfolio's sec_type, a constant that is wrong for a REAL
    position and stays until the real row's settlementTypeID is printed;
  * the stop eToro rewrote on the real BTC fill: the stamp and the fill
    message's line, "Stop moved by eToro: it holds 75745.80, not the
    79934.97 sent (10.0% below the entry)" (its own argument, stop_moved,
    since 2026-09-27).

Nothing here flips a switch, ticks a class, arms a config or sends an
order.

Run with:  python manage.py test tests.test_real_account_measured
"""
import inspect
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program.engine.etoro_client import BASE, EtoroTrader
from tests.test_etoro_client import (ELIG_BTC, PORTFOLIO_ROW, ROW_BTC_LIVE,
                                     SEARCH_AAPL, SEARCH_BTC,
                                     _clear_eligibility, _client,
                                     _elig_route, _lookup_router,
                                     _real_btc_lookup)

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
REAL_DELETE_URL = f"{BASE}/api/v3/trading/execution/orders/1596774177"
#: the measured answer, byte for byte
REAL_DELETE_202 = ("DELETE", "/api/v3/trading/execution/orders/1596774177",
                   202, {"orderId": 1596774177, "referenceId": ""})
DEMO_DELETE_202 = ("DELETE",
                   "/api/v3/trading/execution/demo/orders/1596774177", 202,
                   {"orderId": 1596774177, "referenceId": ""})


def _aapl_held(status_id=11, name="WaitingForMarket"):
    """orders:lookup (no segment) of order 1596774177 on the real account,
    2026-09-26. Printed: status {11, WaitingForMarket}, asset {AAPL, 1001,
    USD, settlementType REAL, leverage 1, long}, requestedAmount 13.64,
    frozenAmount 14.64, openStopLossRate / openTakeProfitRate 0.0.
    Composed: positionExecutions [] (the held shape the demo printed,
    D2b-i), and the body after the DELETE — this one with {7, Canceled}:
    the adapter printed the state, not the body."""
    return {"orderId": 1596774177,
            "status": {"id": status_id, "name": name, "errorCode": 0},
            "asset": {"symbol": "AAPL", "instrumentId": 1001,
                      "currency": "USD", "settlementType": "REAL",
                      "leverage": 1, "side": "long"},
            "requestedAmount": 13.64, "frozenAmount": 14.64,
            "openStopLossRate": 0.0, "openTakeProfitRate": 0.0,
            "positionExecutions": []}


def _deletes(fake):
    return [c for c in fake.calls if c[0] == "DELETE"]


class TheRealDeleteTests(SimpleTestCase):
    """The v3 DELETE on the real segment: the spelling with no segment,
    202 {orderId, referenceId ""}, then {7, Canceled} — the demo answer.
    It raised here (LookupError, the table empty) until 2026-09-26."""

    def test_the_real_delete_url_is_the_measured_spelling(self):
        live, fake = _client([], env="live")
        self.assertEqual(EtoroTrader._V3_EXEC_REAL_SEG, {"orders": ""})
        self.assertEqual(live._v3_exec_order("1596774177"), REAL_DELETE_URL)
        demo, _ = _client([])
        self.assertEqual(demo._v3_exec_order("1596774177"),
                         f"{BASE}/api/v3/trading/execution/demo/orders/"
                         f"1596774177")
        self.assertEqual(fake.calls, [], "composing a URL asked the wire")

    def test_cancel_order_on_a_real_client_proves_canceled(self):
        live, fake = _client([REAL_DELETE_202], env="live")
        _lookup_router(fake, by_order=[(200, _aapl_held()),
                                       (200, _aapl_held(7, "Canceled"))])
        with mock.patch("time.sleep"):
            self.assertIs(live.cancel_order("1596774177"), True)
        self.assertEqual([c[0] for c in fake.calls], ["GET", "DELETE", "GET"])
        first, delete, proof = fake.calls
        self.assertEqual(first[1], f"{BASE}/api/v2/trading/info/orders:lookup")
        self.assertEqual(first[2]["params"], {"orderId": "1596774177"})
        self.assertEqual(delete[1], REAL_DELETE_URL)
        self.assertIn("x-request-id", delete[2]["headers"])
        self.assertNotIn("json", delete[2])
        self.assertEqual(proof[2]["params"], {"orderId": "1596774177"})
        for _m, url, _k in fake.calls:
            self.assertNotIn("/demo/", url)
            self.assertNotIn("/real/", url)

    def test_a_real_delete_the_venue_refuses_is_false_as_on_demo(self):
        """The refusal body is unmeasured on both worlds: any code but
        200/202/204 is False, one DELETE sent, nothing proven."""
        live, fake = _client([("DELETE", "/api/v3/trading/execution/orders/",
                               404, {})], env="live")
        _lookup_router(fake, by_order=(200, _aapl_held()))
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="ERROR"):
            self.assertIs(live.cancel_order("1596774177"), False)
        self.assertEqual([c[1] for c in _deletes(fake)], [REAL_DELETE_URL])

    def test_a_status_nobody_can_read_sends_nothing(self):
        """[lens 1, 2026-09-26] A lookup that answers with no readable
        status (id 0) is "cannot read", as the 404 is: False, one GET,
        no DELETE — on both worlds."""
        for env in ("demo", "live"):
            with self.subTest(env=env):
                t, fake = _client([REAL_DELETE_202, DEMO_DELETE_202], env=env)
                _lookup_router(fake, by_order=(200, {
                    "orderId": 1596774177, "positionExecutions": []}))
                with mock.patch("time.sleep"), \
                        self.assertLogs("bot_program.engine.etoro_client",
                                        level="ERROR") as cm:
                    self.assertIs(t.cancel_order("1596774177"), False)
                self.assertEqual(_deletes(fake), [])
                self.assertEqual([c[0] for c in fake.calls], ["GET"])
                self.assertTrue(any("no readable status" in line
                                    for line in cm.output))

    def test_an_order_the_lookup_reads_as_a_close_is_never_deleted(self):
        """[lens 1, 2026-09-26] A DELETE on a CLOSE order (type 19) is
        unmeasured on both worlds; the demo lookup reads none (404,
        2026-09-23). Should a lookup read one — as etoroOrderTypeId, the
        lookup's own key, or orderType, the close answer's — nothing is
        sent. The open order's measured type (18) still goes."""
        for env in ("demo", "live"):
            for key in ("etoroOrderTypeId", "orderType"):
                with self.subTest(env=env, key=key):
                    t, fake = _client([REAL_DELETE_202, DEMO_DELETE_202],
                                      env=env)
                    _lookup_router(fake, by_order=(200, dict(_aapl_held(),
                                                             **{key: 19})))
                    with mock.patch("time.sleep"), \
                            self.assertLogs("bot_program.engine.etoro_client",
                                            level="ERROR") as cm:
                        self.assertIs(t.cancel_order("1596774177"), False)
                    self.assertEqual(_deletes(fake), [])
                    self.assertTrue(any("CLOSE order (type 19)" in line
                                        for line in cm.output))
        live, fake = _client([REAL_DELETE_202], env="live")
        _lookup_router(fake, by_order=[
            (200, dict(_aapl_held(), etoroOrderTypeId=18)),
            (200, dict(_aapl_held(7, "Canceled"), etoroOrderTypeId=18))])
        with mock.patch("time.sleep"):
            self.assertIs(live.cancel_order("1596774177"), True)
        self.assertEqual([c[1] for c in _deletes(fake)], [REAL_DELETE_URL])


class TheTickWithdrawsALiveEntryTests(TestCase):
    """The working-entry state machine over the REAL EtoroTrader on the
    LIVE segment, beside the same machine on demo: an aged held order is
    withdrawn by the same cancel_order (lookup first, DELETE, Canceled
    proven), with the same words and no alert — only the URL differs.
    While the real spelling raised, the live row stayed WORKING and the
    tick alerted daily. The row is composed from the measured order:
    0.04 AAPL, requestedAmount 13.64 / 0.04 = 341.00."""

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        self.user = User.objects.create_user("real_held", password="x")
        User.objects.create_user("real_staff", password="x", is_staff=True)
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="REAL", mode="live",
            symbols=["AAPL"], capital=Decimal("2249.98"), enabled=True)

    def _row(self, broker_env):
        from bot_program.models import AssetBotTrade
        since = (timezone.now() - timedelta(hours=27)).isoformat()
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("0.04"), entry_price=Decimal("341.00"),
            stop_loss=Decimal("330.77"), take_profit=Decimal("351.23"),
            status="OPEN", paper=False, broker_order_id="1596774177",
            metadata={"entry_working": True, "qty_requested": 0.04,
                      "protective_order_ids": [], "protective_stop_id": "",
                      "protected": False, "entry_working_since": since,
                      "initial_stop_loss": 330.77, "broker": "etoro",
                      "broker_env": broker_env})

    @staticmethod
    def _venue(env):
        t, fake = _client([REAL_DELETE_202 if env == "live"
                           else DEMO_DELETE_202], env=env)
        _lookup_router(fake, by_order=[(200, _aapl_held()),
                                       (200, _aapl_held()),
                                       (200, _aapl_held(7, "Canceled"))])
        return t, fake

    def _tick(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with mock.patch(ROUTER, return_value=client), mock.patch("time.sleep"):
            StockBot(self.cfg).manage_positions()

    @staticmethod
    def _titles():
        from alerts.models import Notification
        return list(Notification.objects.values_list("title", flat=True))

    def test_an_aged_live_held_order_is_withdrawn_exactly_as_on_demo(self):
        seen = {}
        for env, broker_env, url in (
                ("demo", "paper", f"{BASE}/api/v3/trading/execution/demo/"
                                  f"orders/1596774177"),
                ("live", "live", REAL_DELETE_URL)):
            with self.subTest(env=env):
                trade = self._row(broker_env)
                t, fake = self._venue(env)
                self._tick(t)
                trade.refresh_from_db()
                self.assertEqual(trade.status, "CANCELED")
                self.assertNotIn("entry_working", trade.metadata)
                self.assertNotIn("entry_unresolved_notified_at",
                                 trade.metadata)
                self.assertEqual([c[1] for c in _deletes(fake)], [url])
                self.assertEqual([c for c in fake.calls if c[0] == "POST"],
                                 [], "a withdrawal sent an order")
                self.assertEqual(self._titles(), [], "an alert was raised")
                seen[env] = (trade.metadata["entry_withdrawn_reason"],
                             trade.reason.splitlines()[-1])
        self.assertEqual(seen["live"], seen["demo"])
        self.assertEqual(seen["live"][0], "still working after 26h")

    def test_the_kill_switch_withdraws_a_live_held_order_and_never_posts(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        trade = self._row("live")
        t, fake = self._venue("live")
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            _close_asset_trade(trade, timezone.now())
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CANCELED")
        self.assertEqual(trade.metadata["entry_withdrawn_reason"],
                         "EMERGENCY FLATTEN")
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [])
        self.assertEqual([c[1] for c in _deletes(fake)], [REAL_DELETE_URL])


class TheOnePromiseTests(TestCase):
    """execute_entry's alert for a LEVERED order eToro holds, and the TAKE
    TRADE note for a WORKING row: one promise on both worlds since the
    real DELETE is measured. Both said "on live the tick alerts daily
    instead" while the real spelling raised. The entry harness is
    tests/test_etoro_leverage.TheEntryPassesItThroughTests's (a LIVE stock
    config at 2x, the real adapter on a demo wire, "stock" stated proven
    for this test only)."""

    def setUp(self):
        from tests.test_etoro_leverage import _book
        from tests.test_execution_trust import _cfg as _live_cfg
        from tests.test_execution_trust import _instrument, _signal, _user
        self.user = _user("real_lev")
        self.cfg = _live_cfg(self.user, name="REALLEV")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {"leverage": 2}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="lev_rule")
        _book(self.user)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _cand(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_desk_seam import _client as _mock_client
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        return cand

    def _execute(self, cand, t):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    def test_the_levered_working_alert_makes_one_promise(self):
        from bot_program.models import AssetBotTrade
        from tests.test_etoro_leverage import (POSTED, RATES, _account,
                                               _etoro, _switch)
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        held = {"status": {"id": 11, "name": "WaitingForMarket",
                           "errorCode": 0},
                "positionExecutions": [], "openStopLossRate": 0.0,
                "openTakeProfitRate": 0.0}
        t, _ = _etoro([SEARCH_AAPL, RATES, POSTED,
                       ("GET", "orders:lookup", 200, held)])
        with mock.patch("bot_program.notifications.notify_staff") as staff:
            res = self._execute(cand, t)
        self.assertIsNotNone(res)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertTrue(trade.metadata.get("entry_working"))
        alerts = [c.kwargs for c in staff.call_args_list
                  if "order is WORKING at eToro" in c.kwargs.get("title", "")]
        self.assertEqual(len(alerts), 1, staff.call_args_list)
        self.assertIn("AAPL: a 2x order is WORKING at eToro",
                      alerts[0]["title"])
        body = alerts[0]["body"]
        self.assertIn("— eToro is holding it. The 5-minute tick polls it and "
                      "withdraws it if it is still unfilled after 26h. The "
                      "legs ride the order body", body)
        for gone in ("unmeasured", "demo segment", "on live",
                     "alerts daily"):
            self.assertNotIn(gone, body)
        src = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
               / "base.py").read_text(encoding="utf-8")
        self.assertNotIn("the live DELETE spelling is unmeasured", src)

    def test_the_take_trade_note_makes_one_promise(self):
        """The note lives in manual_trade._execute; the file text is read
        (execute_take_trade is a wrapper)."""
        manual = (Path(settings.BASE_DIR) / "bot_program"
                  / "manual_trade.py").read_text(encoding="utf-8")
        self.assertNotIn("withdrawal is NOT attested", manual)
        self.assertNotIn("the tick alerts daily instead of withdrawing",
                         manual)
        self.assertNotIn('not getattr(client, "demo", True)', manual)
        self.assertIn("books the fill when it prints; it is withdrawn if "
                      "it is ", manual)

    def test_an_immediate_fill_with_a_moved_stop_is_stamped_and_told(self):
        """The venue holds the stop FARTHER from the entry than the one
        sent (the real BTC fill's shape, on the AAPL fixture): the row
        keeps the SENT stop as its risk denominator, stamps both levels,
        and the fill message names both; the staff alert is NOT sent
        beside it (ONE message, 2026-09-27). Nothing is resized, closed or
        sent again."""
        from bot_program.models import AssetBotTrade
        from tests.test_etoro_leverage import (_account, _etoro,
                                               _order_posts, _switch)
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        sent = float(cand.stop)
        held = round(sent * 0.97, 2)
        self.assertLess(held, sent)
        t, fake = _etoro(echo_stop=held)
        with mock.patch("bot_program.notifications.notify_bot_fill_open") \
                as fill, \
                mock.patch("bot_program.notifications.notify_staff") as staff:
            res = self._execute(cand, t)
        self.assertIsNotNone(res)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(trade.metadata["stop_rewritten_by_venue"],
                         {"sent": sent, "held": held})
        self.assertEqual(float(trade.metadata["initial_stop_loss"]), sent)
        self.assertEqual(float(trade.entry_price), 100.0)
        words = (f"Stop moved by eToro: it holds {held:.2f}, not the "
                 f"{sent:.2f} sent "
                 f"({abs(100.0 - held) / 100.0 * 100:.1f}% below the entry)")
        self.assertEqual(fill.call_args.kwargs["stop_moved"], words)
        self.assertEqual(fill.call_args.kwargs["rule_name"], trade.rule_name)
        # the fill message went out, so it is the one message
        self.assertFalse(any("the venue rewrote the stop"
                             in c.kwargs.get("title", "")
                             for c in staff.call_args_list))
        self.assertEqual(len(_order_posts(fake)), 1)
        self.assertFalse([c for c in fake.calls
                          if "market-close" in c[1] or c[0] in ("PATCH",
                                                                "DELETE")])

    def test_an_immediate_fill_whose_message_is_not_delivered_alerts_once(
            self):
        """The failure path keeps the staff alert: the fill message was
        not delivered (a muted owner, a refusal), so the staff alert is the
        one message, in the fill message's own words."""
        from bot_program.models import AssetBotTrade
        from tests.test_etoro_leverage import _account, _etoro, _switch
        _switch(True)
        _account(self.user, cash=100000)
        cand = self._cand()
        sent = float(cand.stop)
        held = round(sent * 0.97, 2)
        t, _fake = _etoro(echo_stop=held)
        with mock.patch("bot_program.notifications.notify_bot_fill_open",
                        return_value=False), \
                mock.patch("bot_program.notifications.notify_staff") as staff:
            res = self._execute(cand, t)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        alerts = [c.kwargs for c in staff.call_args_list
                  if "the venue rewrote the stop" in c.kwargs.get("title", "")]
        self.assertEqual(len(alerts), 1, staff.call_args_list)
        self.assertEqual(alerts[0]["body"], (
            f"Stop moved by eToro: it holds {held:.2f}, not the {sent:.2f} "
            f"sent ({abs(100.0 - held) / 100.0 * 100:.1f}% below the "
            f"entry). The fill message was not delivered, so this is the "
            f"one notice. The loss at this stop is not the risk the entry "
            f"was sized for; read the position at eToro (trade #{trade.id} "
            f"on the platform)."))
        self.assertEqual(alerts[0]["url"], f"/forensics/{trade.id}/")


class TheTakeTradeNoteIsRunOnBothWorldsTests(TestCase):
    """[lens 3, 2026-09-26] The TAKE TRADE note for a WORKING row, RUN: the
    lane on the REAL EtoroTrader, once on the demo world and once on the
    live one, the venue holding the order both times ("crypto" stated
    proven, so the pin stands whatever ETORO_PROVEN ships). The two notes
    are the same, word for word: the live caveat went with the refusal it
    described."""

    def setUp(self):
        from django.core.cache import cache
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _quote)
        cache.clear()
        self.user = User.objects.create_user("real_note", password="x")
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"crypto"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _note(self, env):
        from django.core.cache import cache
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade, EtoroAccount
        from tests.test_etoro_leverage import _account
        from tests.test_take_trade_live import _signal
        cache.clear()
        _clear_eligibility()
        EtoroAccount.objects.filter(user=self.user).delete()
        acct = _account(self.user, cash=100000)
        if env == "live":
            # the sync's cells, read in the world this row now trades
            acct.demo = False
            acct.last_margin_world = "live"
            acct.save(update_fields=["demo", "last_margin_world"])
        elig = (ELIG_BTC if env == "demo"
                else _elig_route([ROW_BTC_LIVE], world="live"))
        t, fake = _client([SEARCH_BTC, elig], env=env)
        held = {"orderId": "1596774177", "symbol": "BTCUSD", "side": "BUY",
                "executedQty": "0.0", "avgPrice": "0.0",
                "status": "PENDING", "working": True, "raw": {}}
        with mock.patch.object(t, "ticker",
                               return_value={"lastPrice": "60000"}), \
                mock.patch.object(t, "market_order",
                                  return_value=held) as mo, \
                mock.patch(ROUTER, return_value=t):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        mo.assert_called_once()
        self.assertTrue(out.get("working"), out)
        self.assertEqual(_deletes(fake), [])
        AssetBotTrade.objects.filter(config=self.cfg).delete()
        return out["protection_note"]

    def test_the_working_note_is_the_same_on_both_worlds(self):
        demo = self._note("demo")
        live = self._note("live")
        self.assertEqual(live, demo)
        self.assertIn("5-minute tick watches it", live)
        for gone in ("NOT attested", "alerts daily", "live segment"):
            self.assertNotIn(gone, live)


class TheSmokeLinesTests(TestCase):
    """etoro_smoke on a LIVE row names the real writes as measured: the
    close POST (the 405 kept as its first attestation) and the DELETE,
    composed and never called; the PATCH is the one write still never
    sent on the real segment. The run stays GET-only."""

    def test_the_close_and_delete_lines_on_a_live_row(self):
        from tests.test_etoro_smoke import ROUTES, _FakeSession, _keyed
        user = User.objects.create_user("real_smoke", password="x")
        _keyed(user)
        fake = _FakeSession(ROUTES, (200, {}))
        out = StringIO()
        with mock.patch.object(EtoroTrader, "_sess", lambda self: fake):
            call_command("etoro_smoke", user="real_smoke", stdout=out)
        body = out.getvalue()
        self.assertIn(f"{BASE}/api/v1/trading/execution/market-close-orders/"
                      f"positions/<positionId>", body)
        self.assertIn("real path attested by GET → 405 on 2026-09-22 "
                      "(_V1_EXEC_REAL_SEG); the POST itself measured on the "
                      "real account 2026-09-26 22:03:24 UTC: position "
                      "3588477891 answered orderForClose{orderID 1596736969, "
                      "orderType 19, statusID 1}, proven by the OPEN order's "
                      "positionExecutions[0].state turning 'closed'", body)
        self.assertNotIn("has never been sent", body)
        self.assertIn(f"{BASE}/api/v3/trading/execution/orders/<orderId>",
                      body)
        self.assertNotIn("real v3 spelling not attested", body)
        self.assertIn("measured 2026-09-26 22:03:11 UTC on the real account: "
                      "202 {orderId 1596774177, referenceId ''}", body)
        self.assertIn("status {id 7, Canceled}", body)
        # [lens 3] the POST and the lookup lead with what the REAL account
        # answered; the demo-only facts stay under the demo date
        self.assertIn("measured 2026-09-26 on the real account, at 1x only: "
                      "accepted with an orderId — 1596774177 (AAPL 0.04, "
                      "held) and 1596774178 (BTC 0.0002, filled at once); "
                      "measured 2026-09-23 on the demo segment: 2xx, body",
                      body)
        self.assertIn("measured 2026-09-26 on the real account: 200 by "
                      "?orderId=<int>; {id 11, WaitingForMarket} and {id 7, "
                      "Canceled} read, a fill's held stop on "
                      "positionExecutions[0]; measured 2026-09-23 on the "
                      "demo segment: 200 by ?orderId=<int>, 404 by "
                      "?referenceId=", body)
        for demo_only in ("filled in 200 ms", "a 2x order locked",
                          "4/Rejected (errorCode 720)", "400 by ?token="):
            line = next(ln for ln in body.splitlines() if demo_only in ln)
            real_half = line.split(
                "measured 2026-09-23 on the demo segment")[0]
            self.assertIn("on the real account", real_half, demo_only)
            self.assertNotIn(demo_only, real_half)
        self.assertNotIn("on the demo segment and 2026-09-26", body)
        self.assertEqual(body.count("real segment never sent; measured "
                                    "2026-09-23 on the demo segment"), 1)
        self.assertEqual({m for m, _u, _k in fake.calls}, {"GET"})


class TheCryptoProofTests(SimpleTestCase):
    """ETORO_PROVEN carries "crypto" since 2026-09-26: the BTC
    fill-and-close measured on the REAL account (test_proof_crypto in
    tests/test_etoro_client.py) — stronger than the demo sitting the rule
    asked for. Proven at 1x: ETORO_PROVEN_LEVERAGE stays empty, which binds
    the attack mode's chooser alone — a typed multiplier is not held to it
    (TheTypedMultiplierIsNotHeldTests)."""

    def setUp(self):
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_crypto_is_proven_at_one_x_and_its_proof_is_pinned(self):
        from bot_program.asset_engine.base import (ETORO_PROVEN,
                                                   ETORO_PROVEN_LEVERAGE,
                                                   proven_leverage)
        self.assertIn("crypto", ETORO_PROVEN)
        self.assertEqual(ETORO_PROVEN_LEVERAGE, {})
        self.assertEqual(proven_leverage("crypto"), 1)
        src = (Path(settings.BASE_DIR) / "tests"
               / "test_etoro_client.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("    def test_proof_crypto(self):"), 1)
        proof = src[src.index("    def test_proof_crypto(self):"):]
        self.assertIn("MEASURED ON THE REAL ACCOUNT", proof[:400])

    def test_the_gate_lets_a_1x_crypto_buy_through_and_refuses_the_rest(self):
        """A real client, the measured LIVE BTC row on the wire: a BUY
        clears the proof and the row's caps; a SELL still needs "short"; a
        stock still needs its own proof. No order POST either way."""
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import AssetBot
        t, fake = _client([SEARCH_BTC,
                           _elig_route([ROW_BTC_LIVE], world="live")],
                          env="live")
        gate = AssetBot._etoro_entry_refusal
        self.assertEqual(gate(t, "BTCUSD", "BUY", 0.0002, 84145.8, "crypto"),
                         ("", ""))
        code, why = gate(t, "BTCUSD", "SELL", 0.0002, 84145.8, "crypto")
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("(crypto, SELL)", why)
        self.assertIn("['short']", why)
        code, why = gate(t, "AAPL", "BUY", 0.04, 341.0, "stock")
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("['stock']", why)
        self.assertEqual([c for c in fake.calls if "/orders" in c[1]], [])


class TheTypedMultiplierIsNotHeldTests(TestCase):
    """[lens 1, 2026-09-26] "crypto" in ETORO_PROVEN clears the class-token
    gate at ANY multiplier: ETORO_PROVEN_LEVERAGE binds the attack mode's
    chooser alone (proven_leverage reads 1). A TYPED extras["leverage"] = 2
    on a crypto config is judged as every typed number is — the switch,
    the 2x class ceiling, the own book, then the gate — and clears them
    all once etoro_leverage_live is ON, although no levered order has met
    the real account. Pinned so the words cannot drift from the code;
    holding a typed number to the proven one is an operator decision."""

    def test_the_chooser_reads_one_and_a_typed_two_clears_the_gates(self):
        from bot_program.asset_engine.base import (AssetBot,
                                                   judge_order_leverage,
                                                   proven_leverage)
        from tests.test_etoro_leverage import _book, _switch
        from tests.test_execution_trust import _cfg as _live_cfg
        from tests.test_execution_trust import _user
        self.assertEqual(proven_leverage("crypto"), 1)
        user = _user("typed_crypto")
        cfg = _live_cfg(user, "crypto", name="TYPED2")
        cfg.extras = {"leverage": 2}
        cfg.save(update_fields=["extras"])
        _book(user)
        lev, why = judge_order_leverage(cfg, "crypto", "etoro")
        self.assertIsNone(lev)
        self.assertIn("etoro_leverage_live is OFF", why)
        _switch(True)
        self.assertEqual(judge_order_leverage(cfg, "crypto", "etoro"),
                         (2, ""))
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        t, fake = _client([SEARCH_BTC,
                           _elig_route([ROW_BTC_LIVE], world="live")],
                          env="live")
        self.assertEqual(AssetBot._etoro_entry_refusal(
            t, "BTCUSD", "BUY", 0.0002, 84145.8, "crypto", leverage_hint=2),
            ("", ""))
        self.assertEqual([c for c in fake.calls if "/orders" in c[1]], [])


class TheSecTypeLabelTests(SimpleTestCase):
    """broker_portfolio labels every row 'CFD'. MEASURED 2026-09-26: the
    REAL BTC position 3588477891 read 'CFD', market_price 0.0, currency
    ''. The /portfolio row carries no settlement word — only
    settlementTypeID, printed once (0, a demo GLDM CFD row) — so the code
    stays and says why. The row below is the measured demo row's shape
    with the real position's ids (composed)."""

    def test_a_real_position_still_reads_cfd_and_the_source_says_why(self):
        row = dict(PORTFOLIO_ROW, positionID=3588477891, instrumentID=100000,
                   units=0.0002, openRate=84145.8, amount=16.83,
                   orderID=1596774178)
        t, fake = _client([("GET", "/api/v1/trading/info/portfolio", 200,
                            {"clientPortfolio": {"positions": [row]}})],
                          env="live")
        rows = t.broker_portfolio()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["sec_type"], rows[0]["market_price"],
                          rows[0]["currency"], rows[0]["qty"],
                          rows[0]["avg_cost"]),
                         ("CFD", 0.0, "", 0.0002, 84145.8))
        self.assertEqual(fake.calls[0][1],
                         f"{BASE}/api/v1/trading/info/portfolio")
        src = inspect.getsource(EtoroTrader.broker_portfolio)
        for needle in ("3588477891", "settlementTypeID", "'REAL'",
                       "has never been printed", '"sec_type": "CFD"'):
            self.assertIn(needle, src, needle)


class TheStopMovedLineTests(SimpleTestCase):
    """stop_moved_words: the fill notification's line for a stop the venue
    rewrote, with the numbers measured on the real BTC fill."""

    def test_the_measured_btc_rewrite_reads_as_one_line(self):
        from bot_program.asset_engine.base import stop_moved_words
        meta = {"stop_rewritten_by_venue": {"sent": 79934.97,
                                            "held": 75745.8}}
        self.assertEqual(stop_moved_words(meta, Decimal("84145.8")),
                         "Stop moved by eToro: it holds 75745.80, not the "
                         "79934.97 sent (10.0% below the entry)")
        self.assertEqual(stop_moved_words(meta, Decimal("84145.8"),
                                          asset_class="crypto",
                                          symbol="BTCUSD"),
                         "Stop moved by eToro: it holds 75745.80, not the "
                         "79934.97 sent (10.0% below the entry)")
        self.assertEqual(stop_moved_words(meta, None),
                         "Stop moved by eToro: it holds 75745.80, not the "
                         "79934.97 sent")
        self.assertEqual(stop_moved_words({}, Decimal("84145.8")), "")
        self.assertEqual(stop_moved_words(None, Decimal("84145.8")), "")
        self.assertEqual(stop_moved_words(
            {"stop_rewritten_by_venue": {"sent": None, "held": 1}}, 1), "")
        self.assertEqual(stop_moved_words(
            {"stop_rewritten_by_venue": "x"}, 1), "")
        # [lens 1, lens 3] eToro's 0.0001 "no stop" sentinel, or a zero, is
        # NO stop — never "held 0.0001 (100.00% from entry)"
        for none_held in (0.0001, 0.0):
            self.assertEqual(stop_moved_words(
                {"stop_rewritten_by_venue": {"sent": 79934.97,
                                             "held": none_held}},
                Decimal("84145.8")),
                "No stop at eToro: it holds none, not the 79934.97 sent")


class TheHeldFillCarriesTheLineTests(TestCase):
    """The working path with the real BTC numbers: a held order that fills
    at 84145.8 with the stop sent at 79934.97 and held at 75745.8 is
    stamped by _finish_working_entry and announced with the line. The
    venue's reading is the REAL adapter's order_status over the measured
    lookup body (tests/test_etoro_client._real_btc_lookup)."""

    def test_the_real_btc_rewrite_is_stamped_and_told(self):
        from bot_program.asset_engine.crypto_bot import CryptoBot
        from bot_program.models import AssetBotConfig, AssetBotTrade
        user = User.objects.create_user("real_btc", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="crypto", name="REALBTC", mode="live",
            symbols=["BTCUSD"], capital=Decimal("2249.98"), enabled=True)
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("0.0002"), entry_price=Decimal("84142.07"),
            stop_loss=Decimal("79934.97"), take_profit=Decimal("88349.17"),
            status="OPEN", paper=False, broker_order_id="1596774178",
            rule_name="btc_rule",
            metadata={"entry_working": True, "qty_requested": 0.0002,
                      "protective_order_ids": [], "protected": False,
                      "initial_stop_loss": 79934.97})
        t, fake = _client([], env="live")
        _lookup_router(fake, by_order=(200, _real_btc_lookup("open")))
        st = t.order_status("1596774178")
        self.assertEqual((st["state"], st["filled"], st["avgPrice"],
                          st["positionId"], st["venueStopLoss"]),
                         ("filled", 0.0002, 84145.8, "3588477891", 75745.8))
        bot = CryptoBot(cfg)
        with mock.patch("bot_program.notifications.notify_bot_fill_open") \
                as fill, \
                mock.patch("bot_program.notifications.notify_staff") as staff:
            bot._finish_working_entry(trade, t, qty=st["filled"],
                                      price=st["avgPrice"], source="broker",
                                      venue=st)
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["stop_rewritten_by_venue"],
                         {"sent": 79934.97, "held": 75745.8})
        self.assertEqual(float(trade.metadata["initial_stop_loss"]), 79934.97)
        self.assertEqual(trade.metadata["protective_trade_id"], "3588477891")
        self.assertTrue(trade.metadata["protected"])
        self.assertEqual(float(trade.entry_price), 84145.8)
        self.assertEqual(fill.call_args.kwargs["rule_name"], "btc_rule")
        self.assertEqual(fill.call_args.kwargs["stop_moved"],
                         "Stop moved by eToro: it holds 75745.80, not the "
                         "79934.97 sent (10.0% below the entry)")
        # the fill message went out (the notifier is mocked, and a mock
        # answers truthy): it is the one message, no staff alert beside it
        self.assertEqual(sum("the venue rewrote the stop"
                             in c.kwargs.get("title", "")
                             for c in staff.call_args_list), 0)
        self.assertEqual([c[0] for c in fake.calls], ["GET"],
                         "a fill reading sent something")
