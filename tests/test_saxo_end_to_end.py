"""The whole money path on Saxo, driven against a FAKE WIRE.

Written before the operator has a single credential, because the one thing
no unit test covers is the SEAM: the real sync, the real router, the real
adapter, the real close chooser and the real vision, joined together, with
only the HTTP layer replaced. Every other Saxo test mocks the adapter or
the client; this one mocks nothing above the socket.

WHAT IT DRIVES, in order, exactly as tomorrow evening will:

  1. sync_saxo_accounts reads a keyed, connected row -> the five cells and
     one history row land, through the real SaxoTrader.
  2. /treasury/ shows that capital, and no divergence, because the broker's
     holdings and the platform's rows agree.
  3. broker_router hands a live config a real SaxoTrader for a symbol the
     Saxo row claims.
  4. market_order places an entry with both brackets and reports the fill,
     the position id and the named legs.
  5. The engine's own close chooser asks the venue how it nets and closes
     by PositionId — the defect that would otherwise have booked a row
     CLOSED while Saxo still held both lots.
  6. closing_fill reads the exit out of closedpositions.
  7. /treasury/ shows the divergence when the two accounts of the world
     disagree.

THE FAKE WIRE answers the paths Saxo documents and nothing else: a request
the adapter makes to a path this file does not know raises, so a silent
change of endpoint fails here rather than at 22:00 against a real key.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bot_program.broker_vision import vision
from bot_program.engine import broker_router as router
from bot_program.engine.saxo_client import SaxoTrader
from bot_program.models import SaxoAccount

UIC, ATYPE = 211, "Stock"
SYMBOL = "AAPL"


class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {"X-Correlation": "e2e#1#x#2"}

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class FakeWire:
    """Saxo, as far as the adapter can tell. Every documented path the money
    path touches, and a loud failure for anything else."""

    def __init__(self):
        self.calls = []
        self.orders = {}
        self.next_order = 1000
        self.positions = []          # port/v1/positions rows
        self.closed = []             # port/v1/closedpositions rows
        self.activities = {}         # order id -> audit rows
        self.netting = "FifoEndOfDay"
        self.equity = 50000.0

    # ── helpers the test drives the fake with ────────────────────────────
    def hold(self, symbol=SYMBOL, qty=10.0, open_price=200.0, pos_id="P1"):
        self.positions.append({
            "PositionId": pos_id,
            "PositionBase": {"Uic": UIC, "AssetType": ATYPE, "Amount": qty,
                             "OpenPrice": open_price, "Status": "Open"},
            "PositionView": {"CurrentPrice": open_price * 1.05,
                             "ProfitLossOnTrade": 50.0,
                             "MarketValue": qty * open_price,
                             "ExposureCurrency": "USD"},
            "DisplayAndFormat": {"Symbol": f"{symbol}:xnas", "Currency": "USD"},
        })
        return pos_id

    def _order(self, body):
        oid = str(self.next_order)
        self.next_order += 1
        kids = []
        for child in body.get("Orders") or []:
            kid = str(self.next_order)
            self.next_order += 1
            kids.append({"OrderId": kid})
        # A market order fills at once, as SIM does in hours.
        self.activities[oid] = [
            {"OrderId": oid, "Status": "Placed", "SubStatus": "Confirmed"},
            {"OrderId": oid, "Status": "FinalFill", "SubStatus": "Confirmed",
             "FilledAmount": body.get("Amount"), "AveragePrice": 201.5,
             "PositionId": "P1"},
        ]
        out = {"OrderId": oid}
        if kids:
            out["Orders"] = kids
        return out

    # ── the wire ─────────────────────────────────────────────────────────
    def _route(self, method, url, kw):
        self.calls.append((method, url))
        body = kw.get("json") or {}
        if "port/v1/clients/me" in url:
            return _Resp(200, {"ClientKey": "CK", "DefaultAccountKey": "AK",
                               "DefaultAccountId": "1INET",
                               "DefaultCurrency": "EUR",
                               "PositionNettingProfile": self.netting,
                               "PositionNettingMode": "EndOfDay"})
        if "port/v1/accounts/me" in url:
            return _Resp(200, {"Data": [{"AccountKey": "AK",
                                         "Currency": "USD"}]})
        if "root/v1/sessions/capabilities" in url:
            return _Resp(200, {"AuthenticationLevel": "Authenticated"})
        if "ref/v1/instruments/details/" in url:
            return _Resp(200, {
                "Uic": UIC, "AssetType": ATYPE, "TickSize": 0.01,
                "LotSize": 1, "LotSizeType": "OddLotsAllowed",
                "MinimumTradeSize": 1, "AmountDecimals": 0,
                "SupportedOrderTypes": ["Market", "Limit", "Stop",
                                        "TrailingStop"]})
        if "ref/v1/instruments" in url:
            return _Resp(200, {"Data": [{
                "Identifier": UIC, "Symbol": f"{SYMBOL}:xnas",
                "Description": "Apple Inc.", "AssetType": ATYPE,
                "SummaryType": "Instrument", "PrimaryListing": UIC}]})
        if "trade/v1/infoprices" in url:
            return _Resp(200, {"Quote": {"Bid": 201.0, "Ask": 201.2,
                                         "Mid": 201.1, "DelayedByMinutes": 15,
                                         "PriceTypeBid": "Indicative"},
                               "PriceInfoDetails": {"LastTraded": 201.1},
                               "DisplayAndFormat": {"Symbol": SYMBOL}})
        if "port/v1/balances" in url:
            return _Resp(200, {"TotalValue": self.equity, "Currency": "EUR",
                               "CashBalance": self.equity})
        if "port/v1/closedpositions" in url:
            return _Resp(200, {"Data": self.closed})
        if "port/v1/positions/" in url:
            pid = url.split("port/v1/positions/")[1].split("?")[0]
            for p in self.positions:
                if p["PositionId"] == pid:
                    return _Resp(200, p)
            return _Resp(404, {"ErrorCode": "NotFound", "Message": "gone"})
        if "port/v1/positions" in url:
            return _Resp(200, {"Data": self.positions})
        if "cs/v1/audit/orderactivities" in url:
            oid = url.split("OrderId=")[1].split("&")[0]
            return _Resp(200, {"Data": self.activities.get(oid, [])})
        if "trade/v2/orders" in url and method == "POST":
            return _Resp(200, self._order(body))
        if "trade/v2/orders" in url and method == "PATCH":
            return _Resp(200, {"OrderId": str(body.get("OrderId"))})
        if "trade/v2/orders" in url and method == "DELETE":
            return _Resp(200, {"Orders": [{"OrderId": "x"}]})
        raise AssertionError(
            f"the adapter asked Saxo for a path this fake does not know: "
            f"{method} {url} — if that is a real Saxo endpoint, teach the "
            f"fake; if not, the adapter is wrong")

    def get(self, url, **kw):
        return self._route("GET", url, kw)

    def post(self, url, **kw):
        return self._route("POST", url, kw)

    def patch(self, url, **kw):
        return self._route("PATCH", url, kw)

    def delete(self, url, **kw):
        return self._route("DELETE", url, kw)

    def asked(self, fragment):
        return [u for _m, u in self.calls if fragment in u]


def a_row(user, *, flags=("stock",), sim=True):
    acct = SaxoAccount.objects.create(
        user=user, sim=sim, label="Main",
        redirect_uri="https://h.example.net/brokers/saxo/callback/")
    acct.set_credentials("app", "secret")
    for cls in flags:
        setattr(acct, {"stock": "is_primary_for_stocks",
                       "forex": "is_primary_for_forex",
                       "commodity": "is_primary_for_commodity",
                       "crypto": "is_primary_for_crypto"}[cls], True)
    now = timezone.now()
    acct.set_tokens("bearer-abc", "refresh-abc",
                    now + timedelta(seconds=1200),
                    refresh_expires_at=now + timedelta(seconds=2400))
    acct.connected = True
    acct.save()
    return acct


def a_trade(user, symbol=SYMBOL, *, broker="saxo", meta=None, qty=10.0):
    from bot_program.asset_models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, name="e2e_stock",
        defaults={"asset_class": "stock", "mode": "live", "symbols": [symbol],
                  "capital": Decimal("10000"), "base_currency": "EUR",
                  "enabled": True})
    m = {"broker": broker}
    m.update(meta or {})
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side="BUY",
        qty=Decimal(str(qty)), entry_price=Decimal("200"), status="OPEN",
        paper=False, metadata=m)


class TheWholeMoneyPathTests(TestCase):
    """Nothing above the socket is mocked."""

    def setUp(self):
        from django.core.cache import cache
        from bot_program.engine import saxo_client as sc
        cache.clear()
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()
        self.user = User.objects.create_user("e2e_u", password="x")
        self.acct = a_row(self.user)
        self.wire = FakeWire()
        self._patch = mock.patch.object(SaxoTrader, "_sess",
                                        return_value=self.wire)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol=SYMBOL, defaults={"name": SYMBOL, "asset_class": "stock",
                                     "exchange": "NASDAQ"})

    def _fresh(self):
        return User.objects.get(pk=self.user.pk)

    # ── 1. the sync ──────────────────────────────────────────────────────
    def _sync(self):
        from bot_program.tasks import sync_saxo_accounts
        with mock.patch("bot_program.tasks._follow_the_account"), \
             mock.patch("bot_program.tasks._shock_trigger"):
            return sync_saxo_accounts.__wrapped__.__wrapped__()

    def test_the_sync_reads_the_real_adapter_and_lands_the_cells(self):
        self.wire.hold()
        out = self._sync()
        self.acct.refresh_from_db()
        self.assertEqual(out["attempted"], 1)
        self.assertEqual(out["stored"], 1)
        self.assertEqual(float(self.acct.last_equity), 50000.0)
        self.assertEqual(self.acct.last_equity_currency, "EUR")
        self.assertEqual(len(self.acct.broker_positions), 1)
        held = self.acct.broker_positions[0]
        self.assertEqual(held["symbol"], SYMBOL)
        self.assertEqual(held["qty"], 10.0)
        self.assertEqual(held["market_price"], 210.0)
        from bot_program.equity_models import BrokerEquityReading
        row = BrokerEquityReading.objects.get(broker="saxo",
                                              account_pk=self.acct.pk)
        self.assertEqual(row.env, "paper")       # the row is on SIM
        # And it asked Saxo the documented way.
        self.assertTrue(self.wire.asked("port/v1/balances"))
        self.assertTrue(self.wire.asked("port/v1/positions"))

    # ── 2. the vision agrees with the broker ─────────────────────────────
    def test_the_vision_shows_that_capital_and_no_divergence(self):
        self.wire.hold()
        self._sync()
        a_trade(self.user)
        v = vision(self._fresh())
        row = v["brokers"][0]
        self.assertEqual(row["kind"], "saxo")
        self.assertTrue(row["is_book"])
        self.assertEqual(row["equity"]["value"], 50000.0)
        self.assertEqual(row["held_n"], 1)
        d = v["divergence"][0]
        self.assertTrue(d["known"])
        self.assertEqual(len(d["agree"]), 1)
        self.assertEqual((d["only_broker"], d["only_platform"]), ([], []))
        self.assertEqual(v["blockers"], [])

    # ── 3. the router hands back a real adapter ─────────────────────────
    def test_the_router_hands_a_live_config_a_saxo_trader(self):
        client = router.client_for_symbol(self._fresh(), SYMBOL)
        self.assertIsInstance(client, SaxoTrader)
        self.assertEqual(client.env, "sim")
        self.assertEqual(router.broker_name_for_symbol(self._fresh(), SYMBOL),
                         "saxo")

    # ── 4. an entry, with both brackets ─────────────────────────────────
    def test_an_entry_reports_its_fill_its_position_and_its_legs(self):
        client = router.client_for_symbol(self._fresh(), SYMBOL)
        with mock.patch("bot_program.engine.saxo_client.time.sleep"):
            res = client.market_order(SYMBOL, "BUY", 10, stop_loss=190.0,
                                      take_profit=215.0,
                                      client_order_id="sig-e2e")
        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(res["executedQty"], "10.0")
        self.assertEqual(res["avgPrice"], "201.5")
        self.assertEqual(res["protectiveTradeId"], "P1")
        self.assertEqual(len(res["protectiveOrders"]), 2)
        self.assertIn("protectiveStopId", res)
        self.assertIn("protectiveTargetId", res)
        self.assertNotIn("working", res)
        # The ticker the engine reads before sizing speaks the platform's key.
        self.assertIn("lastPrice", client.ticker(SYMBOL))

    # ── 5. the close the venue actually needs ───────────────────────────
    def _close(self, trade, client):
        from bot_program.asset_engine.base import AssetBot
        stub = mock.Mock(asset_class="stock")
        return AssetBot._submit_close_order(stub, trade, client, "close-e2e")

    def test_a_fifo_end_of_day_close_goes_by_position_id(self):
        """The defect this closes: an opposite market order does NOT net
        under FifoEndOfDay, so the platform would have booked the row
        CLOSED while Saxo still held both lots."""
        pid = self.wire.hold()
        client = router.client_for_symbol(self._fresh(), SYMBOL)
        trade = a_trade(self.user, meta={"protective_trade_id": pid})
        with mock.patch("bot_program.engine.saxo_client.time.sleep"):
            res = self._close(trade, client)
        self.assertEqual(res["positionId"], pid)
        sent = [u for m, u in self.wire.calls if m == "POST"]
        self.assertTrue(sent)
        # One order, and it named the position rather than opening a hedge.
        self.assertEqual(len(sent), 1)

    def test_a_real_time_netting_account_closes_the_ordinary_way(self):
        self.wire.netting = "FifoRealTime"
        pid = self.wire.hold()
        client = router.client_for_symbol(self._fresh(), SYMBOL)
        trade = a_trade(self.user, meta={"protective_trade_id": pid})
        with mock.patch("bot_program.engine.saxo_client.time.sleep"):
            res = self._close(trade, client)
        # market_order's shape, not close_position's
        self.assertIn("executedQty", res)
        self.assertEqual(res["side"], "SELL")

    def test_no_position_id_sends_nothing_at_all(self):
        """It used to log the disaster and send the opposite order anyway —
        which under FifoEndOfDay leaves BOTH lots live while the row books
        CLOSED. Now nothing is sent and the row goes to the retry drain,
        which reads Saxo's own book."""
        client = router.client_for_symbol(self._fresh(), SYMBOL)
        trade = a_trade(self.user)          # no protective_trade_id
        before = len([1 for m, u in self.wire.calls
                      if m == "POST" and "trade/v2/orders" in u])
        with mock.patch("bot_program.engine.saxo_client.time.sleep"):
            with self.assertLogs("bot_program.engine.venue_close",
                                 level="ERROR") as cm:
                with self.assertRaises(RuntimeError):
                    self._close(trade, client)
        self.assertTrue(any("NOTHING has been sent" in m for m in cm.output))
        after = len([1 for m, u in self.wire.calls
                     if m == "POST" and "trade/v2/orders" in u])
        self.assertEqual(after, before, "no order reached the wire")

    # ── 6. the exit price comes from the broker ─────────────────────────
    def test_closing_fill_reads_the_exit_out_of_closed_positions(self):
        self.wire.closed = [{"ClosedPosition": {
            "OpeningPositionId": "P1", "ClosingPositionId": "P2",
            "OpenPrice": 200.0, "ClosingPrice": 207.25, "Amount": 10,
            "ExecutionTimeClose": "2026-09-21T15:00:00Z"}}]
        client = router.client_for_symbol(self._fresh(), SYMBOL)
        trade = a_trade(self.user, meta={"protective_trade_id": "P1"})
        fill = client.closing_fill(trade)
        self.assertEqual(fill["price"], 207.25)
        self.assertEqual(fill["qty"], 10.0)
        self.assertEqual(fill["source"], "saxo:closedpositions")

    # ── 7. and when the two disagree ────────────────────────────────────
    def test_a_position_the_broker_does_not_report_is_a_blocker(self):
        self.wire.hold()                      # the broker holds AAPL
        self._sync()
        a_trade(self.user)                    # the platform holds AAPL
        a_trade(self.user, symbol="TSLA")     # ...and TSLA, which Saxo does not
        v = vision(self._fresh())
        d = v["divergence"][0]
        self.assertEqual([p["symbol"] for p in d["only_platform"]], ["TSLA"])
        self.assertTrue(any("does NOT report" in b for b in v["blockers"]))

    def test_the_page_renders_the_whole_story(self):
        self.wire.hold()
        self._sync()
        a_trade(self.user)
        self.client.login(username="e2e_u", password="x")
        page = self.client.get(reverse("treasury_page"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Saxo Bank")
        self.assertContains(page, "50,000.00")
        self.assertContains(page, SYMBOL)

    # ── and the page that must never touch a broker ─────────────────────
    def test_no_page_asks_the_broker_anything(self):
        """Broker I/O lives in the sync task and nowhere else. A render
        path that opened a socket would be a page that hangs when the
        broker does."""
        self.wire.hold()
        self._sync()
        a_trade(self.user)
        before = len(self.wire.calls)
        self.client.login(username="e2e_u", password="x")
        self.client.get(reverse("treasury_page"))
        self.client.get(reverse("brokers_page"))
        vision(self._fresh())
        self.assertEqual(len(self.wire.calls), before,
                         "a render path called the broker")
