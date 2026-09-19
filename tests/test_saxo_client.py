"""SaxoTrader against a fake OpenAPI: every field name it reads, every one
it sends, and the honesty of its fill verdicts.

Every endpoint and field below is what developer.saxo documents
(2026-09-17, two readers, rechecked — scratchpad saxo_spec.md), so a test
here fails when the adapter drifts from the documentation, not when it
drifts from itself. The four facts that only SIM can settle are named in
the adapter's docstrings and probed by `saxo_smoke`, not asserted here.

WHAT THESE TESTS CONFRONT

  * The wire: SIM and LIVE bases from the row's flag, Bearer on every
    call, X-Request-ID on writes only, a 401 never JSON-parsed, a 429
    carrying its reset, a 400 carrying Saxo's ErrorCode.
  * Identity: ClientKey / DefaultAccountKey / account Currency / netting
    profile read once and reused on every portfolio call.
  * Resolution: (Uic, AssetType) from a keyword search pinned to the
    listing, cached; a best match that is not the ticker is a
    LookupError, never a trade on the wrong instrument.
  * Prices and bars: last trade for stocks, mid for FX; delay returned
    beside the price; bid/ask bars averaged; twelve columns, oldest
    first, Horizon in minutes, Count capped at 1200.
  * Orders: the body Saxo documents (AccountKey, Uic, AssetType, BuySell,
    Amount on the lot grid, Market, ManualOrder false, DayOrder,
    ExternalReference) with brackets as opposite-side GoodTillCancel
    children whose stop type is the instrument's own spelling and whose
    prices sit on the tick; the fill read from the audit log; PENDING,
    PARTIALLY_FILLED, CANCELLED, REJECTED and UNKNOWN each told apart.
  * Brackets and closes: the stop leg found through the position under
    FifoEndOfDay and through the order otherwise; PATCH re-sends every
    relevant field; an explicit close names the PositionId only under
    FifoEndOfDay.
  * closing_fill: ClosingPrice from closedpositions by OpeningPositionId,
    the audit log's FinalFill as the fallback, None when neither answers.

AND THE KEYS THE ENGINE ACTUALLY READS. An adversarial review of the first
draft found twelve defects that every test here passed over, all of one
kind: the adapter spoke the documentation's contract line while the
platform reads its own spellings. `ticker` returned "last" where every
consumer reads "lastPrice" (so a Saxo bot could never enter); the named
legs were `protective_stop_id` where base.py reads `protectiveStopId`;
`closing_fill` read camelCase metadata where base.py writes snake_case;
`cancel_order` returned a truthy dict where base.py tests `is False`. The
fixtures were shaped by the adapter instead of by the consumers, so
nothing failed. Every assertion below that names a key now names the
CONSUMER's key, and the classes at the end hold one defect each:
ConsumerKeyTests, PartialAcceptanceTests, WorkingOrderTests,
AmountRefusalTests, RealTimeNettingTests.
"""
import json
from unittest import mock

from django.test import SimpleTestCase

from bot_program.engine import saxo_client as sc
from bot_program.engine.saxo_client import (
    SaxoApiError, SaxoAuthError, SaxoRateLimited, SaxoTrader)


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {"X-Correlation": "abc#1#def#2"}

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class _FakeSession:
    """Routes (METHOD, url-substring) -> (status, payload). Records calls."""

    def __init__(self, routes=None, default=(200, {})):
        self.routes = list(routes or [])
        self.default = default
        self.calls = []

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for m, sub, status, payload in self.routes:
            if m == method and sub in url:
                return _Resp(status, payload)
        return _Resp(*self.default)

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def patch(self, url, **kw):
        return self._hit("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._hit("DELETE", url, **kw)

    def sent(self, method, sub):
        """The JSON body of the first call matching (method, sub)."""
        for m, url, kw in self.calls:
            if m == method and sub in url:
                return kw.get("json")
        return None

    def urls(self, method=None):
        return [u for m, u, _ in self.calls if method is None or m == method]


class _Acct:
    def __init__(self, sim=True):
        self.sim = sim


CLIENT_ME = ("GET", "port/v1/clients/me", 200, {
    "ClientKey": "CK==", "DefaultAccountKey": "AK==", "DefaultAccountId": "1INET",
    "DefaultCurrency": "EUR", "PositionNettingProfile": "FifoEndOfDay",
    "PositionNettingMode": "EndOfDay"})
ACCOUNTS_ME = ("GET", "port/v1/accounts/me", 200, {"Data": [
    {"AccountKey": "OTHER==", "Currency": "DKK"},
    {"AccountKey": "AK==", "Currency": "USD"}]})
SEARCH_EURUSD = ("GET", "ref/v1/instruments?Keywords=EURUSD", 200, {"Data": [
    {"Identifier": 21, "Symbol": "EURUSD", "AssetType": "FxSpot",
     "SummaryType": "Instrument", "PrimaryListing": 21}]})
SEARCH_AAPL = ("GET", "ref/v1/instruments?Keywords=AAPL", 200, {"Data": [
    {"Identifier": 9999, "Symbol": "AAPL:xmil", "AssetType": "Stock",
     "SummaryType": "Instrument", "PrimaryListing": 211},
    {"Identifier": 211, "Symbol": "AAPL:xnas", "AssetType": "Stock",
     "SummaryType": "Instrument", "PrimaryListing": 211}]})
DETAILS_EURUSD = ("GET", "ref/v1/instruments/details/21/FxSpot", 200, {
    "Uic": 21, "AssetType": "FxSpot", "TickSize": 0.00005, "MinimumTradeSize": 1000,
    "AmountDecimals": 0, "LotSizeType": "NotUsed",
    "SupportedOrderTypes": ["Market", "Limit", "Stop", "TrailingStop", "StopLimit"]})
DETAILS_AAPL = ("GET", "ref/v1/instruments/details/211/Stock", 200, {
    "Uic": 211, "AssetType": "Stock", "TickSizeScheme": {
        "DefaultTickSize": 0.01, "Elements": [{"HighPrice": 1, "TickSize": 0.0001}]},
    "LotSize": 1, "LotSizeType": "OddLotsAllowed", "MinimumTradeSize": 1,
    "AmountDecimals": 0,
    "SupportedOrderTypes": ["Limit", "Market", "StopIfTraded", "TrailingStopIfTraded", "StopLimit"]})


def trader(routes, sim=True, **kw):
    sess = _FakeSession(routes=[CLIENT_ME, ACCOUNTS_ME] + list(routes), **kw)
    return SaxoTrader(_Acct(sim=sim), token="tok-123", session=sess), sess


class TheWireTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_sim_and_live_bases_follow_the_row(self):
        t, _ = trader([], sim=True)
        self.assertTrue(t.base.endswith("/sim/openapi"))
        t, _ = trader([], sim=False)
        self.assertTrue(t.base.endswith("gateway.saxobank.com/openapi"))

    def test_bearer_on_reads_request_id_on_writes_only(self):
        t, sess = trader([("GET", "root/v1/sessions/capabilities", 200,
                           {"AuthenticationLevel": "Authenticated"})])
        self.assertTrue(t.ping())
        _m, _u, kw = sess.calls[0]
        self.assertEqual(kw["headers"]["Authorization"], "Bearer tok-123")
        self.assertNotIn("X-Request-ID", kw["headers"])
        t.cancel_order("77")
        _m, _u, kw = [c for c in sess.calls if c[0] == "DELETE"][0]
        self.assertEqual(len(kw["headers"]["X-Request-ID"]), 32)
        self.assertNotIn("tok-123", json.dumps(kw.get("json")))

    def test_a_401_is_never_parsed(self):
        t, _ = trader([("GET", "port/v1/balances", 401, None)])
        with self.assertRaises(SaxoAuthError):
            t.balances()

    def test_a_429_carries_its_reset(self):
        sess = _FakeSession()
        sess.routes = [CLIENT_ME, ACCOUNTS_ME]
        t = SaxoTrader(_Acct(), token="x", session=sess)
        with mock.patch.object(sess, "_hit", return_value=_Resp(
                429, {"ErrorCode": "RateLimitExceeded"},
                headers={"X-RateLimit-Session-Reset": "17", "X-Correlation": "c"})):
            with self.assertRaises(SaxoRateLimited) as cm:
                t._get("port/v1/balances")
        self.assertEqual(cm.exception.reset_s, 17)

    def test_a_400_carries_saxos_error_code(self):
        t, _ = trader([("GET", "port/v1/balances", 400, {
            "ErrorCode": "InvalidModelState", "Message": "One or more properties",
            "ModelState": {"ClientKey": ["required"]}})])
        with self.assertRaises(SaxoApiError) as cm:
            t.balances()
        self.assertEqual(cm.exception.code, "InvalidModelState")
        self.assertIn("ClientKey", str(cm.exception))
        self.assertEqual(cm.exception.correlation, "abc#1#def#2")

    def test_ping_is_false_when_the_session_cannot_answer(self):
        t, _ = trader([("GET", "root/v1/sessions/capabilities", 401, None)])
        self.assertFalse(t.ping())


class IdentityTests(SimpleTestCase):

    def test_identity_is_read_once_and_names_the_accounts_currency(self):
        t, sess = trader([])
        ident = t.identity()
        self.assertEqual(ident["client_key"], "CK==")
        self.assertEqual(ident["account_key"], "AK==")
        self.assertEqual(ident["currency"], "USD")       # the account's, not DKK
        self.assertEqual(ident["netting_profile"], "FifoEndOfDay")
        t.identity()
        self.assertEqual(len([u for u in sess.urls("GET") if "clients/me" in u]), 1)


class ResolveTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_fx_resolves_to_its_uic_and_is_cached(self):
        t, sess = trader([SEARCH_EURUSD, DETAILS_EURUSD])
        with mock.patch.object(SaxoTrader, "_asset_type_for", return_value="FxSpot"), \
             mock.patch.object(SaxoTrader, "_exchange_for", return_value=None):
            uic, atype, details = t.resolve("EURUSD")
            t.resolve("EURUSD")
        self.assertEqual((uic, atype), (21, "FxSpot"))
        self.assertEqual(details["MinimumTradeSize"], 1000)
        self.assertEqual(len([u for u in sess.urls("GET") if "ref/v1/instruments?" in u]), 1)
        self.assertIn("AssetTypes=FxSpot", sess.urls("GET")[0])

    def test_a_stock_is_pinned_to_its_listing_and_the_primary_wins(self):
        t, sess = trader([SEARCH_AAPL, DETAILS_AAPL])
        with mock.patch.object(SaxoTrader, "_asset_type_for", return_value="Stock"), \
             mock.patch.object(SaxoTrader, "_exchange_for", return_value="NASDAQ"):
            uic, atype, _ = t.resolve("AAPL")
        self.assertEqual((uic, atype), (211, "Stock"))
        self.assertIn("ExchangeId=NASDAQ", sess.urls("GET")[0])

    def test_a_best_match_that_is_not_the_ticker_is_refused(self):
        t, _ = trader([("GET", "ref/v1/instruments?Keywords=KO", 200, {"Data": [
            {"Identifier": 1, "Symbol": "KOF:xnys", "AssetType": "Stock",
             "SummaryType": "Instrument", "PrimaryListing": 1}]})])
        with mock.patch.object(SaxoTrader, "_asset_type_for", return_value="Stock"), \
             mock.patch.object(SaxoTrader, "_exchange_for", return_value=None):
            with self.assertRaises(LookupError):
                t.resolve("KO")

    def test_nothing_found_is_a_lookup_error(self):
        t, _ = trader([("GET", "ref/v1/instruments?Keywords=ZZZZ", 200, {"Data": []})])
        with mock.patch.object(SaxoTrader, "_asset_type_for", return_value="Stock"), \
             mock.patch.object(SaxoTrader, "_exchange_for", return_value=None):
            with self.assertRaises(LookupError):
                t.resolve("ZZZZ")


def _fx(routes, **kw):
    """A trader with EURUSD already resolvable."""
    t, sess = trader([SEARCH_EURUSD, DETAILS_EURUSD] + list(routes), **kw)
    sc._UIC_CACHE[("EURUSD", "FxSpot")] = (21, "FxSpot", DETAILS_EURUSD[3])
    sc._SYMBOL_BY_UIC[(21, "FxSpot")] = "EURUSD"
    return t, sess


def _stock(routes, **kw):
    t, sess = trader([SEARCH_AAPL, DETAILS_AAPL] + list(routes), **kw)
    sc._UIC_CACHE[("AAPL", "Stock")] = (211, "Stock", DETAILS_AAPL[3])
    sc._SYMBOL_BY_UIC[(211, "Stock")] = "AAPL"
    return t, sess


class PricesTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_a_stock_quote_reads_the_last_trade_and_its_delay(self):
        t, sess = _stock([("GET", "trade/v1/infoprices?Uic=211", 200, {
            "Quote": {"Bid": 596.5, "Ask": 597, "Mid": 596.75, "DelayedByMinutes": 15,
                      "PriceTypeBid": "Indicative", "MarketState": "Open"},
            "PriceInfoDetails": {"LastTraded": 596.8}})])
        tk = t.ticker("AAPL")
        # lastPrice is the key asset_engine, reconcile, the kill switch and
        # manual_trade all read. "last" is an alias, not the contract.
        self.assertEqual((tk["lastPrice"], tk["bid"], tk["ask"]),
                         ("596.8", "596.5", "597.0"))
        self.assertEqual(tk["last"], tk["lastPrice"])
        self.assertEqual(tk["delayed_minutes"], 15)
        self.assertEqual(tk["price_type"], "Indicative")
        url = [u for u in sess.urls("GET") if "infoprices" in u][0]
        self.assertIn("AssetType=Stock", url)
        self.assertIn("AccountKey=AK", url)

    def test_fx_has_no_trades_so_last_is_the_mid(self):
        t, _ = _fx([("GET", "trade/v1/infoprices?Uic=21", 200, {
            "Quote": {"Bid": 1.1, "Ask": 1.1002, "Mid": 1.1001, "DelayedByMinutes": 0},
            "PriceInfoDetails": {"LastTraded": 0}})])
        tk = t.ticker("EURUSD")
        self.assertEqual(tk["lastPrice"], "1.1001")
        self.assertEqual(tk["delayed_minutes"], 0)

    def test_stock_bars_are_twelve_columns_oldest_first_with_the_horizon(self):
        t, sess = _stock([("GET", "chart/v3/charts?Uic=211", 200, {
            "ChartInfo": {"Horizon": 240},
            "Data": [{"Time": "2026-09-17T08:00:00.000000Z", "Open": 1, "High": 2,
                      "Low": 0.5, "Close": 1.5, "Volume": 100},
                     {"Time": "2026-09-17T12:00:00Z", "Open": 1.5, "High": 1.6,
                      "Low": 1.4, "Close": 1.55, "Volume": 0}]})])
        rows = t.klines("AAPL", "4h", limit=5000)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 12)
        self.assertEqual(rows[0][1:6], ["1.0", "2.0", "0.5", "1.5", "100"])
        self.assertEqual(rows[0][6] - rows[0][0], 240 * 60 * 1000)
        self.assertLess(rows[0][0], rows[1][0])
        url = [u for u in sess.urls("GET") if "chart/v3" in u][0]
        self.assertIn("Horizon=240", url)
        self.assertIn("Count=1200", url)          # capped, never 5000

    def test_fx_bars_are_the_mid_of_bid_and_ask(self):
        t, _ = _fx([("GET", "chart/v3/charts?Uic=21", 200, {"Data": [
            {"Time": "2026-09-17T08:00:00Z", "OpenBid": 1.0, "OpenAsk": 1.2,
             "HighBid": 1.5, "HighAsk": 1.7, "LowBid": 0.9, "LowAsk": 1.1,
             "CloseBid": 1.3, "CloseAsk": 1.5}]})])
        rows = t.klines("EURUSD", "1h")
        self.assertEqual(rows[0][1:6], ["1.1", "1.6", "1.0", "1.4", "0"])

    def test_an_unknown_interval_is_refused(self):
        t, _ = _fx([])
        with self.assertRaises(ValueError):
            t.klines("EURUSD", "7m")

    def test_depth_when_saxo_carries_it_else_the_synthetic_book(self):
        t, _ = _fx([("GET", "trade/v1/infoprices?Uic=21", 200, {
            "Quote": {"Bid": 1.1, "Ask": 1.2},
            "MarketDepth": {"Bid": [1.1, 1.09], "BidSize": [5, 6],
                            "Ask": [1.2, 1.21], "AskSize": [7, 8]}})])
        book = t.order_book("EURUSD", limit=1)
        self.assertEqual(book, {"bids": [["1.1", "5"]], "asks": [["1.2", "7"]]})
        t, _ = _fx([("GET", "trade/v1/infoprices?Uic=21", 200, {
            "Quote": {"Bid": 1.1, "Ask": 1.2}, "MarketDepth": {}})])
        book = t.order_book("EURUSD", limit=3)
        self.assertEqual(len(book["bids"]), 3)
        self.assertEqual(book["bids"][0][0], "1.1")


class AccountTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_net_liquidation_is_total_value_in_the_accounts_currency(self):
        t, sess = trader([("GET", "port/v1/balances?", 200, {
            "TotalValue": 100634.36, "Currency": "EUR", "CashBalance": 99000})])
        self.assertEqual(t.net_liquidation(), (100634.36, "EUR"))
        url = [u for u in sess.urls("GET") if "balances" in u][0]
        self.assertIn("ClientKey=CK", url)
        self.assertIn("AccountKey=AK", url)

    def test_net_liquidation_is_none_when_unreadable_or_zero(self):
        t, _ = trader([("GET", "port/v1/balances?", 503, None)])
        self.assertIsNone(t.net_liquidation())
        t, _ = trader([("GET", "port/v1/balances?", 200, {"TotalValue": 0, "Currency": "EUR"})])
        self.assertIsNone(t.net_liquidation())

    def test_positions_keep_only_open_lots_and_read_the_documented_fields(self):
        t, _ = _fx([("GET", "port/v1/positions?", 200, {"Data": [
            {"PositionId": "1", "PositionBase": {"Uic": 21, "AssetType": "FxSpot",
             "Amount": 100000, "OpenPrice": 1.32167, "Status": "Open"},
             "PositionView": {"CurrentPrice": 1.29169, "ProfitLossOnTrade": -2998,
                              "MarketValue": 129169, "ExposureCurrency": "GBP"},
             "DisplayAndFormat": {"Symbol": "EURUSD", "Currency": "USD"}},
            {"PositionId": "2", "PositionBase": {"Uic": 21, "AssetType": "FxSpot",
             "Amount": -50000, "OpenPrice": 1.3, "Status": "Open"},
             "PositionView": {"CurrentPrice": 1.29}, "DisplayAndFormat": {"Symbol": "EURUSD"}},
            {"PositionId": "3", "PositionBase": {"Uic": 21, "AssetType": "FxSpot",
             "Amount": 100000, "OpenPrice": 1.3, "Status": "Closed"},
             "PositionView": {}}]})])
        pos = t.get_positions()
        self.assertEqual([(p["symbol"], p["qty"], p["side"], p["position_id"]) for p in pos],
                         [("EURUSD", 100000.0, "BUY", "1"), ("EURUSD", 50000.0, "SELL", "2")])
        self.assertEqual(pos[0]["entry"], 1.32167)
        self.assertEqual(pos[0]["pnl"], -2998.0)
        port = t.broker_portfolio()
        self.assertEqual(port[0]["sec_type"], "CASH")
        self.assertEqual(port[0]["market_value"], 129169.0)
        self.assertEqual(port[0]["currency"], "USD")
        self.assertEqual(len(port), 2)

    def test_broker_portfolio_is_none_when_unreadable_positions_raise(self):
        t, _ = trader([("GET", "port/v1/positions?", 503, None)])
        self.assertIsNone(t.broker_portfolio())
        with self.assertRaises(SaxoApiError):
            t.get_positions()


FILLED = ("GET", "cs/v1/audit/orderactivities?OrderId=1000001", 200, {"Data": [
    {"OrderId": "1000001", "Status": "Placed", "SubStatus": "Confirmed", "Amount": 5000},
    {"OrderId": "1000001", "Status": "FinalFill", "SubStatus": "Confirmed",
     "FillAmount": 5000, "FilledAmount": 5000, "AveragePrice": 1.1001,
     "PositionId": "19968201"}]})


class MarketOrderTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_the_body_is_the_one_saxo_documents_with_brackets_as_children(self):
        t, sess = _fx([("POST", "trade/v2/orders", 200, {
            "OrderId": "1000001", "Orders": [{"OrderId": "1000002"}, {"OrderId": "1000003"}]}),
            FILLED])
        with mock.patch.object(sc.time, "sleep"):
            out = t.market_order("EURUSD", "BUY", 4990, stop_loss=1.09001,
                                 take_profit=1.12001, client_order_id="sig-42")
        body = sess.sent("POST", "trade/v2/orders")
        self.assertEqual(body["AccountKey"], "AK==")
        self.assertEqual((body["Uic"], body["AssetType"], body["BuySell"]), (21, "FxSpot", "Buy"))
        self.assertEqual(body["Amount"], 4990.0)
        self.assertEqual(body["OrderType"], "Market")
        self.assertIs(body["ManualOrder"], False)
        self.assertEqual(body["OrderDuration"], {"DurationType": "DayOrder"})
        self.assertEqual(body["ExternalReference"], "sig-42")
        stop, target = body["Orders"]
        self.assertEqual((stop["OrderType"], stop["BuySell"]), ("Stop", "Sell"))
        self.assertEqual(stop["OrderPrice"], 1.09)             # 1.09001 → nearest 0.00005
        self.assertEqual(stop["OrderDuration"], {"DurationType": "GoodTillCancel"})
        self.assertEqual((stop["Uic"], stop["AssetType"], stop["Amount"], stop["AccountKey"]),
                         (21, "FxSpot", 4990.0, "AK=="))
        self.assertEqual((target["OrderType"], target["OrderPrice"]), ("Limit", 1.12))
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual((out["executedQty"], out["avgPrice"]), ("5000.0", "1.1001"))
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual(out["protectiveOrders"], ["1000002", "1000003"])
        self.assertEqual(out["protectiveTradeId"], "19968201")
        # camelCase: base.py:2725-2727 reads protectiveStopId /
        # protectiveTargetId off the result and writes the snake_case
        # metadata itself.
        self.assertEqual(out["protectiveStopId"], "1000002")
        self.assertEqual(out["protectiveTargetId"], "1000003")
        self.assertNotIn("working", out)          # it filled

    def test_a_stock_uses_the_instruments_own_stop_spelling_and_lot_grid(self):
        t, sess = _stock([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"}), FILLED])
        with mock.patch.object(sc.time, "sleep"):
            t.market_order("AAPL", "SELL", 10.7, stop_loss=200.123, trailing=2.0)
        body = sess.sent("POST", "trade/v2/orders")
        self.assertEqual(body["Amount"], 10.0)                 # lots of 1
        self.assertEqual(body["BuySell"], "Sell")
        stop = body["Orders"][0]
        self.assertEqual(stop["OrderType"], "TrailingStopIfTraded")
        self.assertEqual(stop["BuySell"], "Buy")
        self.assertEqual(stop["OrderPrice"], 200.12)           # 0.01 tick above 1
        self.assertEqual(stop["TrailingStopDistanceToMarket"], 2.0)

    def test_pending_when_the_audit_log_shows_no_fill(self):
        t, _ = _fx([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"}),
                    ("GET", "cs/v1/audit/orderactivities", 200, {"Data": [
                        {"OrderId": "1000001", "Status": "Working"}]})])
        with mock.patch.object(sc.time, "sleep") as slept:
            out = t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(out["status"], "PENDING")
        self.assertEqual(out["executedQty"], "0.0")
        self.assertNotIn("protectedOnFill", out)
        # base.py:2744 books a WORKING row on this flag and polls it;
        # without it an unfilled order became a full-size OPEN position.
        self.assertIs(out["working"], True)
        self.assertEqual(slept.call_count, sc.FILL_ATTEMPTS - 1)

    def test_partial_cancelled_and_rejected_are_told_apart(self):
        cases = [
            ([{"Status": "Fill", "FilledAmount": 2000, "AveragePrice": 1.1, "PositionId": "p"}],
             "PARTIALLY_FILLED", "2000.0"),
            ([{"Status": "Cancelled"}], "CANCELLED", "0.0"),
            ([{"Status": "Placed", "SubStatus": "Rejected"}], "REJECTED", "0.0"),
        ]
        for rows, status, qty in cases:
            with self.subTest(status):
                t, _ = _fx([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"}),
                            ("GET", "cs/v1/audit/orderactivities", 200, {"Data": rows})])
                with mock.patch.object(sc.time, "sleep"):
                    out = t.market_order("EURUSD", "BUY", 5000)
                self.assertEqual((out["status"], out["executedQty"]), (status, qty))

    def test_a_202_is_unknown_and_never_resent(self):
        t, sess = _fx([("POST", "trade/v2/orders", 202, {
            "OrderId": "55024416", "ErrorInfo": {"ErrorCode": "TradeNotCompleted"}})])
        out = t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(out["status"], "UNKNOWN")
        self.assertEqual(out["orderId"], "55024416")
        self.assertIs(out["working"], True)
        self.assertIn("not retried", out["protectionNote"])
        self.assertEqual(len(sess.urls("POST")), 1)
        self.assertFalse(any("orderactivities" in u for u in sess.urls("GET")))

    def test_a_refused_order_raises_with_saxos_code(self):
        t, _ = _fx([("POST", "trade/v2/orders", 400, {
            "ErrorInfo": {"ErrorCode": "OrderValueToSmall", "Message": "too small"}})])
        with self.assertRaises(SaxoApiError) as cm:
            t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(cm.exception.code, "OrderValueToSmall")

    def test_every_write_carries_a_fresh_request_id(self):
        t, sess = _fx([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"}), FILLED])
        with mock.patch.object(sc.time, "sleep"):
            t.market_order("EURUSD", "BUY", 5000)
            t.market_order("EURUSD", "BUY", 5000)
        ids = [kw["headers"]["X-Request-ID"] for m, u, kw in sess.calls if m == "POST"]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])


class BracketTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    POSITION = ("GET", "port/v1/positions/19968201", 200, {
        "PositionId": "19968201", "PositionBase": {
            "Uic": 21, "AssetType": "FxSpot", "Amount": 5000, "Status": "Open",
            "RelatedOpenOrders": [
                {"OrderId": "1000002", "OpenOrderType": "Stop", "OrderPrice": 1.09,
                 "Amount": 5000, "Duration": {"DurationType": "GoodTillCancel"}},
                {"OrderId": "1000003", "OpenOrderType": "Limit", "OrderPrice": 1.12,
                 "Amount": 5000, "Duration": {"DurationType": "GoodTillCancel"}}]}})

    def test_the_stop_leg_is_found_through_the_position_and_moved_on_tick(self):
        """The leg names no instrument; the tick size must still be found
        through the position, or Saxo answers PriceNotInTickSizeIncrements."""
        t, sess = _fx([self.POSITION,
                       ("PATCH", "trade/v2/orders", 200, {"OrderId": "1000002",
                                                          "Orders": [{"OrderId": "1000002"}]})])
        sc._UIC_CACHE.clear()          # a cold worker: nothing resolved here
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()
        res = t.modify_protective("19968201", 1.095027)
        self.assertTrue(res["ok"], res)
        # The tick came from the instrument by (Uic, AssetType) — not from
        # a symbol cache this process never filled.
        self.assertEqual(res["price"], 1.09505)
        body = sess.sent("PATCH", "trade/v2/orders")
        self.assertEqual(body["OrderId"], "1000002")
        self.assertEqual((body["Uic"], body["AssetType"]), (21, "FxSpot"))
        self.assertEqual(body["OrderType"], "Stop")
        self.assertEqual(body["OrderPrice"], 1.09505)
        self.assertEqual(body["Amount"], 5000)
        self.assertEqual(body["AccountKey"], "AK==")
        self.assertEqual(body["OrderDuration"], {"DurationType": "GoodTillCancel"})

    def test_the_target_leg_is_the_limit_and_the_stop_is_untouched(self):
        t, sess = _fx([self.POSITION,
                       ("PATCH", "trade/v2/orders", 200, {"OrderId": "1000003"})])
        res = t.modify_target("19968201", 1.13)
        self.assertTrue(res["ok"], res)
        body = sess.sent("PATCH", "trade/v2/orders")
        self.assertEqual((body["OrderId"], body["OrderType"]), ("1000003", "Limit"))

    def test_under_real_time_netting_the_leg_is_found_through_the_order(self):
        t, sess = _fx([("GET", "port/v1/positions/1000002", 404, {"ErrorCode": "NotFound"}),
                       ("GET", "port/v1/orders/CK==/1000002", 200, {"Data": [
                           {"OrderId": "1000002", "OpenOrderType": "Stop", "Price": 1.09,
                            "Amount": 5000, "Uic": 21, "AssetType": "FxSpot", "BuySell": "Sell",
                            "Duration": {"DurationType": "GoodTillCancel"}}]}),
                       ("PATCH", "trade/v2/orders", 200, {"OrderId": "1000002"})])
        res = t.modify_protective("1000002", 1.1)
        self.assertTrue(res["ok"], res)
        self.assertEqual(sess.sent("PATCH", "trade/v2/orders")["OrderId"], "1000002")

    def test_a_refused_move_reports_saxos_words_and_no_price(self):
        t, _ = _fx([self.POSITION, ("PATCH", "trade/v2/orders", 200, {
            "Orders": [{"ErrorInfo": {"ErrorCode": "TooCloseToMarket", "Message": "too close"}}]})])
        res = t.modify_protective("19968201", 1.1)
        self.assertFalse(res["ok"])
        self.assertIn("TooCloseToMarket", res["reason"])
        self.assertIsNone(res["price"])

    def test_cancel_is_false_when_saxo_refuses_it(self):
        """base.py:1503 tests `cancel(oid) is False`. A dict is never False,
        so the first draft recorded a refused cancel as done — and a stop
        still resting against a flat book OPENS a reverse position."""
        for body in ({"Orders": [{"ErrorInfo": {"ErrorCode": "TooLateToCancelOrder",
                                                "Message": "late"}}]},
                     {"ErrorInfo": {"ErrorCode": "OrderNotFound",
                                    "Message": "gone"}}):
            with self.subTest(body=sorted(body)[0]):
                t, _ = trader([("DELETE", "trade/v2/orders/77", 200, body)])
                with self.assertLogs("bot_program.engine.saxo_client",
                                     level="ERROR"):
                    res = t.cancel_order("77")
                self.assertIs(res, False)
        t, _ = trader([("DELETE", "trade/v2/orders/77", 400, {
            "ErrorCode": "OrderCannotBeCancelledAtThisTime", "Message": "locked"})])
        with self.assertLogs("bot_program.engine.saxo_client", level="ERROR"):
            self.assertIs(t.cancel_order("77"), False)

    def test_cancel_is_true_when_saxo_confirms_it(self):
        t, sess = trader([("DELETE", "trade/v2/orders/77", 200, {"Orders": [{"OrderId": "77"}]})])
        self.assertIs(t.cancel_order("77"), True)
        self.assertIn("AccountKey=AK", sess.urls("DELETE")[0])
        # The success body is undocumented and may be empty: the status
        # code is Saxo's own answer, so an unparseable 2xx is confirmed.
        t, _ = trader([("DELETE", "trade/v2/orders/78", 200, None)])
        self.assertIs(t.cancel_order("78"), True)
        t, _ = trader([("DELETE", "trade/v2/orders/79", 204, None)])
        self.assertIs(t.cancel_order("79"), True)


class ClosingTests(SimpleTestCase):

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_an_explicit_close_names_the_position_under_fifo_end_of_day(self):
        t, sess = _fx([("GET", "port/v1/positions/19968201", 200, {"PositionBase": {
                            "Uic": 21, "AssetType": "FxSpot", "Amount": 5000, "Status": "Open"}}),
                       ("POST", "trade/v2/orders", 200, {"OrderId": "2000001"}),
                       ("GET", "cs/v1/audit/orderactivities?OrderId=2000001", 200, {"Data": [
                           {"Status": "FinalFill", "FilledAmount": 5000, "AveragePrice": 1.105}]})])
        with mock.patch.object(sc.time, "sleep"):
            out = t.close_position("19968201", "EURUSD")
        body = sess.sent("POST", "trade/v2/orders")
        self.assertEqual(body["PositionId"], "19968201")
        leg = body["Orders"][0]
        self.assertEqual((leg["BuySell"], leg["Amount"], leg["OrderType"]), ("Sell", 5000.0, "Market"))
        self.assertEqual((out["status"], out["avgPrice"]), ("FILLED", "1.105"))

    def test_under_real_time_netting_an_opposite_order_is_placed_instead(self):
        client = ("GET", "port/v1/clients/me", 200, dict(CLIENT_ME[3], PositionNettingProfile="FifoRealTime"))
        sess = _FakeSession(routes=[client, ACCOUNTS_ME,
                                    ("GET", "port/v1/positions/9", 200, {"PositionBase": {
                                        "Uic": 21, "AssetType": "FxSpot", "Amount": -5000}}),
                                    ("POST", "trade/v2/orders", 200, {"OrderId": "2000002"})])
        t = SaxoTrader(_Acct(), token="x", session=sess)
        with mock.patch.object(sc.time, "sleep"):
            t.close_position("9", "EURUSD")
        body = sess.sent("POST", "trade/v2/orders")
        self.assertNotIn("PositionId", body)
        self.assertEqual((body["BuySell"], body["Amount"]), ("Buy", 5000.0))

    def _trade(self, **meta):
        return mock.Mock(metadata=meta)

    def test_closing_fill_reads_closing_price_by_opening_position_id(self):
        t, _ = trader([("GET", "port/v1/closedpositions", 200, {"Data": [
            {"ClosedPosition": {"OpeningPositionId": "139597294", "ClosingPositionId": "139694249",
                                "ClosingPrice": 1.09139, "Amount": 300000,
                                "ExecutionTimeClose": "2017-05-02T00:00:00Z"}},
            {"ClosedPosition": {"OpeningPositionId": "19968201", "ClosingPrice": 1.105,
                                "Amount": 5000, "ExecutionTimeClose": "2026-09-17T15:00:00Z"}}]})])
        fill = t.closing_fill(self._trade(protective_trade_id="19968201"))
        self.assertEqual((fill["price"], fill["qty"], fill["source"]),
                         (1.105, 5000.0, "saxo:closedpositions"))

    def test_closing_fill_falls_back_to_the_audit_log_of_the_stop(self):
        t, _ = trader([("GET", "port/v1/closedpositions", 200, {"Data": []}),
                       ("GET", "cs/v1/audit/orderactivities?OrderId=1000002", 200, {"Data": [
                           {"Status": "Placed"},
                           {"Status": "FinalFill", "FilledAmount": 5000, "AveragePrice": 1.09}]})])
        fill = t.closing_fill(self._trade(protective_trade_id="19968201",
                                          protective_stop_id="1000002"))
        self.assertEqual((fill["price"], fill["source"]), (1.09, "saxo:orderactivities"))

    def test_closing_fill_is_none_when_nobody_answers(self):
        t, _ = trader([("GET", "port/v1/closedpositions", 200, {"Data": []}),
                       ("GET", "cs/v1/audit/orderactivities", 200, {"Data": [{"Status": "Working"}]})])
        self.assertIsNone(t.closing_fill(self._trade(protective_trade_id="x",
                                                     protective_stop_id="y")))
        self.assertIsNone(t.closing_fill(self._trade()))


class ConsumerKeyTests(SimpleTestCase):
    """The keys, confronted with the CONSUMERS rather than with this file.

    Read out of asset_engine/base.py and its siblings, not out of the
    adapter: a fixture shaped by the adapter cannot catch a key the
    platform does not read. This is the test the first draft lacked, and
    it is why twelve defects passed a green suite."""

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_the_ticker_key_is_the_one_every_consumer_reads(self):
        import re
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.BASE_DIR)
        readers = ["bot_program/asset_engine/base.py", "bot_program/reconcile_asset.py",
                   "bot_program/pending_closes.py", "bot_program/manual_trade.py",
                   "bot_program/engine/kill_switch.py"]
        for rel in readers:
            body = (root / rel).read_text(encoding="utf-8")
            with self.subTest(rel):
                self.assertIn("lastPrice", body)
        t, _ = _fx([("GET", "trade/v1/infoprices?Uic=21", 200, {
            "Quote": {"Bid": 1.1, "Ask": 1.2, "Mid": 1.15}})])
        self.assertIn("lastPrice", t.ticker("EURUSD"))

    def test_the_result_keys_are_the_ones_the_engine_reads(self):
        """Every key market_order offers is one base.py looks for — a key
        it does not read is a promise nothing keeps."""
        from pathlib import Path

        from django.conf import settings
        body = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                / "base.py").read_text(encoding="utf-8")
        for key in ("protectiveOrders", "protectedOnFill", "protectiveTradeId",
                    "protectiveStopId", "protectiveTargetId", "protectionNote",
                    "working", "executedQty", "avgPrice"):
            with self.subTest(key):
                self.assertIn(f'"{key}"', body)

    def test_the_metadata_keys_closing_fill_reads_are_the_ones_written(self):
        from pathlib import Path

        from django.conf import settings
        body = (Path(settings.BASE_DIR) / "bot_program" / "asset_engine"
                / "base.py").read_text(encoding="utf-8")
        for key in ("protective_trade_id", "protective_stop_id",
                    "protective_target_id", "protective_order_ids"):
            with self.subTest(key):
                self.assertIn(f'entry_meta["{key}"]', body)
        adapter = (Path(settings.BASE_DIR) / "bot_program" / "engine"
                   / "saxo_client.py").read_text(encoding="utf-8")
        self.assertNotIn('meta.get("protectiveTradeId")', adapter)


class PartialAcceptanceTests(SimpleTestCase):
    """An order that EXISTS is never reported as a refusal."""

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_a_400_carrying_an_order_id_is_an_accepted_order(self):
        """Saxo's documented partial acceptance: the master is placed, a
        related order is refused, and the status is 400. Raising there left
        the parent live at Saxo with no row to own it."""
        t, sess = _fx([("POST", "trade/v2/orders", 400, {
            "OrderId": "74994594",
            "Orders": [{"OrderId": "74994595"},
                       {"ErrorInfo": {"ErrorCode": "TooFarFromEntryOrder",
                                      "Message": "Order price is too far"}}]}),
            ("GET", "cs/v1/audit/orderactivities?OrderId=74994594", 200, {"Data": [
                {"Status": "FinalFill", "FilledAmount": 5000, "AveragePrice": 1.1,
                 "PositionId": "p1"}]})])
        with mock.patch.object(sc.time, "sleep"):
            out = t.market_order("EURUSD", "BUY", 5000, stop_loss=1.09,
                                 take_profit=1.12)
        self.assertEqual(out["orderId"], "74994594")
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["protectiveOrders"], ["74994595"])
        # The stop was accepted and the LIMIT refused: the surviving leg
        # must be labelled the stop, not the target.
        self.assertEqual(out["protectiveStopId"], "74994595")
        self.assertNotIn("protectiveTargetId", out)
        self.assertIs(out["protectedOnFill"], False)
        self.assertIn("TooFarFromEntryOrder", out["protectionNote"])
        self.assertEqual(out["raw"]["httpStatus"], 400)

    def test_a_refused_stop_never_labels_the_limit_as_the_stop(self):
        """The first draft labelled by index into the response, so a
        refused stop made the take-profit the 'stop' and the stop rules
        would have moved the target down onto the market."""
        t, _ = _fx([("POST", "trade/v2/orders", 400, {
            "OrderId": "1000001",
            "Orders": [{"ErrorInfo": {"ErrorCode": "TooCloseToMarket"}},
                       {"OrderId": "1000003"}]}),
            ("GET", "cs/v1/audit/orderactivities", 200, {"Data": [
                {"Status": "FinalFill", "FilledAmount": 5000, "AveragePrice": 1.1}]})])
        with mock.patch.object(sc.time, "sleep"):
            out = t.market_order("EURUSD", "BUY", 5000, stop_loss=1.09,
                                 take_profit=1.12)
        self.assertEqual(out["protectiveTargetId"], "1000003")
        self.assertNotIn("protectiveStopId", out)
        self.assertIn("TooCloseToMarket", out["protectionNote"])

    def test_a_400_with_no_order_id_is_still_a_refusal(self):
        t, _ = _fx([("POST", "trade/v2/orders", 400, {
            "ErrorInfo": {"ErrorCode": "InsufficientCash", "Message": "no"}})])
        with self.assertRaises(SaxoApiError) as cm:
            t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(cm.exception.code, "InsufficientCash")

    def test_a_2xx_that_names_no_order_is_a_refusal(self):
        t, _ = _fx([("POST", "trade/v2/orders", 200, {})])
        with self.assertRaises(SaxoApiError):
            t.market_order("EURUSD", "BUY", 5000)


class WorkingOrderTests(SimpleTestCase):
    """A placed order always has an owner, and its brackets are known as
    soon as Saxo accepts them."""

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_an_unfilled_order_reports_its_accepted_brackets(self):
        """They are GTC and already resting at Saxo. Withholding them until
        a fill left the engine holding legs it could neither move nor
        cancel — and `_cancel_protective_orders` returns True on an empty
        list, so a flatten would have left them live."""
        t, _ = _fx([("POST", "trade/v2/orders", 200, {
            "OrderId": "1000001",
            "Orders": [{"OrderId": "1000002"}, {"OrderId": "1000003"}]}),
            ("GET", "cs/v1/audit/orderactivities", 200, {"Data": [
                {"Status": "Working"}]})])
        with mock.patch.object(sc.time, "sleep"):
            out = t.market_order("EURUSD", "BUY", 5000, stop_loss=1.09,
                                 take_profit=1.12)
        self.assertEqual(out["status"], "PENDING")
        self.assertIs(out["working"], True)
        self.assertEqual(out["protectiveOrders"], ["1000002", "1000003"])
        self.assertEqual(out["protectiveStopId"], "1000002")
        self.assertEqual(out["protectiveTargetId"], "1000003")
        # Not protected YET: nothing has filled, so the engine must not
        # skip bot-side management on the strength of it.
        self.assertIs(out["protectedOnFill"], False)

    def test_a_fill_that_cannot_be_read_is_pending_not_failed(self):
        """The order IS placed. Letting the read error escape made the
        engine skip with ORDER_ERROR and write no row at all."""
        t, _ = _fx([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"})])
        with mock.patch.object(SaxoTrader, "_order_activities",
                               side_effect=RuntimeError("socket died")):
            with self.assertLogs("bot_program.engine.saxo_client",
                                 level="WARNING"):
                out = t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(out["orderId"], "1000001")
        self.assertEqual(out["status"], "PENDING")
        self.assertIs(out["working"], True)
        self.assertIn("fill unreadable", out["protectionNote"])

    def test_a_partial_fill_cancelled_afterwards_keeps_its_units(self):
        """Reporting 0 there would leave real units at the broker with no
        row claiming them."""
        t, _ = _fx([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"}),
                    ("GET", "cs/v1/audit/orderactivities", 200, {"Data": [
                        {"Status": "Fill", "FilledAmount": 2000,
                         "AveragePrice": 1.1002, "PositionId": "p9"},
                        {"Status": "Cancelled"}]})])
        with mock.patch.object(sc.time, "sleep"):
            out = t.market_order("EURUSD", "BUY", 5000)
        self.assertEqual(out["status"], "PARTIALLY_FILLED")
        self.assertEqual(out["executedQty"], "2000.0")
        self.assertEqual(out["avgPrice"], "1.1002")
        self.assertNotIn("working", out)


class AmountRefusalTests(SimpleTestCase):
    """Nothing silently changes the size of a trade."""

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_a_size_below_the_minimum_is_refused_not_enlarged(self):
        """400 units on EURUSD (minimum 1 000) was traded as 1 000: two and
        a half times the risk the bot computed from its stop distance."""
        t, sess = _fx([("POST", "trade/v2/orders", 200, {"OrderId": "x"})])
        with self.assertRaises(ValueError) as cm:
            t.market_order("EURUSD", "BUY", 400)
        msg = str(cm.exception)
        self.assertIn("1000", msg)
        self.assertIn("400", msg)
        self.assertIn("2.5x", msg)
        self.assertEqual(sess.urls("POST"), [])

    def test_less_than_one_lot_is_refused(self):
        t, sess = _stock([("POST", "trade/v2/orders", 200, {"OrderId": "x"})])
        with self.assertRaises(ValueError) as cm:
            t.market_order("AAPL", "BUY", 0.4)
        self.assertIn("lots of 1", str(cm.exception))
        self.assertEqual(sess.urls("POST"), [])

    def test_the_lot_grid_only_ever_rounds_down(self):
        t, sess = _stock([("POST", "trade/v2/orders", 200, {"OrderId": "1000001"}),
                          ("GET", "cs/v1/audit/orderactivities", 200, {"Data": [
                              {"Status": "FinalFill", "FilledAmount": 10,
                               "AveragePrice": 200}]})])
        with mock.patch.object(sc.time, "sleep"):
            t.market_order("AAPL", "BUY", 10.7)
        self.assertEqual(sess.sent("POST", "trade/v2/orders")["Amount"], 10.0)


class RealTimeNettingTests(SimpleTestCase):
    """Under FifoRealTime and AverageRealTime a position has no related
    orders — the brackets are free-standing. The movers must find them."""

    def setUp(self):
        sc._UIC_CACHE.clear()
        sc._SYMBOL_BY_UIC.clear()
        sc._DETAILS_CACHE.clear()

    def test_a_position_with_no_legs_falls_through_to_the_order_route(self):
        """The first draft returned the position's empty list and answered
        'no stop leg' — so on exactly the accounts whose brackets are not
        position-related, no stop could ever be moved."""
        t, sess = _fx([
            ("GET", "port/v1/positions/19968201", 200, {"PositionBase": {
                "Uic": 21, "AssetType": "FxSpot", "Amount": 5000,
                "Status": "Open", "RelatedOpenOrders": []}}),
            ("GET", "port/v1/orders/CK==/19968201", 200, {"Data": [
                {"OrderId": "19968201", "OpenOrderType": "Stop", "Amount": 5000,
                 "Uic": 21, "AssetType": "FxSpot", "BuySell": "Sell",
                 "Duration": {"DurationType": "GoodTillCancel"}}]}),
            ("PATCH", "trade/v2/orders", 200, {"OrderId": "19968201"})])
        res = t.modify_protective("19968201", 1.1)
        self.assertTrue(res["ok"], res)
        self.assertTrue(any("port/v1/orders/CK==" in u for u in sess.urls("GET")),
                        "the order route was never tried")

    def test_a_202_on_the_patch_is_not_a_move(self):
        """Recording it as moved would show a level the broker never took."""
        t, _ = _fx([
            ("GET", "port/v1/positions/19968201", 200, {"PositionBase": {
                "Uic": 21, "AssetType": "FxSpot", "Amount": 5000,
                "RelatedOpenOrders": [
                    {"OrderId": "1000002", "OpenOrderType": "Stop",
                     "OrderPrice": 1.09, "Amount": 5000}]}}),
            ("PATCH", "trade/v2/orders", 202, {
                "OrderId": "1000002",
                "ErrorInfo": {"ErrorCode": "TradeNotCompleted"}})])
        res = t.modify_protective("19968201", 1.1)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["price"])
        self.assertIn("did not confirm", res["reason"])

    def test_a_top_level_error_on_the_patch_is_not_a_move(self):
        t, _ = _fx([
            ("GET", "port/v1/positions/19968201", 200, {"PositionBase": {
                "Uic": 21, "AssetType": "FxSpot", "Amount": 5000,
                "RelatedOpenOrders": [
                    {"OrderId": "1000002", "OpenOrderType": "Stop",
                     "OrderPrice": 1.09, "Amount": 5000}]}}),
            ("PATCH", "trade/v2/orders", 200, {
                "ErrorInfo": {"ErrorCode": "OrderNotFound", "Message": "gone"}})])
        res = t.modify_protective("19968201", 1.1)
        self.assertFalse(res["ok"])
        self.assertIn("OrderNotFound", res["reason"])

    def test_a_stop_limit_leg_keeps_its_stop_limit_price(self):
        t, sess = _fx([
            ("GET", "port/v1/positions/19968201", 200, {"PositionBase": {
                "Uic": 21, "AssetType": "FxSpot", "Amount": 5000,
                "RelatedOpenOrders": [
                    {"OrderId": "1000002", "OpenOrderType": "StopLimit",
                     "OrderPrice": 1.09, "StopLimitPrice": 1.0895,
                     "Amount": 5000}]}}),
            ("PATCH", "trade/v2/orders", 200, {"OrderId": "1000002"})])
        res = t.modify_protective("19968201", 1.1)
        self.assertTrue(res["ok"], res)
        self.assertEqual(sess.sent("PATCH", "trade/v2/orders")["StopLimitPrice"],
                         1.0895)

