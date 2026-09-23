"""EtoroTrader against a fake wire (2026-09-17).

No real key has met this adapter yet. These tests therefore pin the three
facts about eToro's API that shape it — read from the public reference and
encoded here so a live key finds behaviour, not guesses:

  1. ORDERS ARE ASYNCHRONOUS. A 200 on POST is an acceptance. The fill is
     read from orders:lookup, keyed by the x-request-id this client sent.
     An order still pending when polling stops is PENDING with no quantity —
     never a fill. OANDA's own history is the warning: "a completely
     unfilled order was booked as a complete fill on both sides".
  2. TWO PATH RULES. v2 omits the environment segment for the real account;
     v1 writes it. A wrong rule is a 404 in production on a real key.
  3. INTEGER instrumentId EVERYWHERE, resolved once and cached; an unknown
     spelling RAISES rather than answering an empty list that reads as "no
     history".

WHAT THEY DO NOT DO

They do not prove the wire format is right — a fake session cannot. They
prove that IF eToro answers as documented, the engine receives the shape
`asset_engine` reads: orderId, status in its refusal vocabulary,
executedQty and avgPrice as strings, protectiveTradeId for the bracket
mover. The first demo key turns these from "as documented" into "as
observed", and any divergence lands here by name.
"""
import uuid
from unittest import mock

from django.test import SimpleTestCase

from bot_program.engine import capabilities as cap
from bot_program.engine.etoro_client import (
    BASE, EtoroTrader, INTERVAL_MAP, STATUS_FILLED, STATUS_REFUSED)


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """Routes (method, url-substring) -> (status, payload). Records calls."""

    def __init__(self, routes=None, default=(200, {})):
        self.routes = list(routes or [])
        self.default = default
        self.calls = []
        self.headers = {}

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


SEARCH_AAPL = ("GET", "/market-data/search", 200,
               [{"instrumentId": 1001, "internalSymbolFull": "AAPL"}])


def _client(routes, env="demo"):
    t = EtoroTrader("api-k", "user-k", env=env)
    fake = _FakeSession(routes)
    t._session = fake
    return t, fake


def _lookup(status, *, units=10.0, avg=190.5, position_id=555):
    return {"status": status, "requestedUnits": units,
            "positionExecutions": [{
                "positionId": position_id, "state": "open",
                "remainingUnits": units, "stopLossRate": 180.0,
                "takeProfitRate": 210.0,
                "openingData": {"avgPrice": avg, "units": units}}]}


class EveryCallCarriesTheHeadersTests(SimpleTestCase):

    def test_request_id_is_a_fresh_uuid_per_call(self):
        t, fake = _client([SEARCH_AAPL,
                           ("GET", "/instruments/rates", 200,
                            {"rates": [{"bid": 1, "ask": 2}]})])
        t.ticker("AAPL")
        t.ticker("AAPL")
        rids = [c[2]["headers"]["x-request-id"] for c in fake.calls]
        for rid in rids:
            uuid.UUID(rid)                     # raises if not a UUID
        self.assertEqual(len(set(rids)), len(rids),
                         "x-request-id was reused; it is the idempotency "
                         "key of an order and must be unique per call")

    def test_a_uuid_client_order_id_becomes_the_request_id(self):
        rid = str(uuid.uuid4())
        self.assertEqual(EtoroTrader._rid(rid), rid)

    def test_a_non_uuid_client_order_id_gets_a_fresh_one(self):
        out = EtoroTrader._rid("bot-42-AAPL")
        uuid.UUID(out)
        self.assertNotEqual(out, "bot-42-AAPL")


class TheTwoPathRulesTests(SimpleTestCase):
    """The segment is a TABLE, and every entry below was MEASURED.

    This class used to assert that v1 writes "real", under the docstring
    "Encoded, not guessed" — and it was guessed. The tests were green because
    they compared the adapter against this author's belief, never against
    eToro; a pinned URL string cannot detect that the belief is wrong, and it
    demonstrably did not. On 2026-09-22 the operator's first real key made
    the save-time probe answer 404, and these status codes were then measured
    with that key, read-only, each beside a known-200 control:

        /api/v1/trading/info/aggregate-portfolio             200
        /api/v1/trading/info/real/aggregate-portfolio        404
        /api/v1/trading/info/portfolio                       200
        /api/v1/trading/info/real/portfolio                  404
        /api/v1/trading/info/pnl                             404
        /api/v1/trading/info/real/pnl                        200
        GET /api/v1/trading/execution/market-close-orders/1  405
        GET /api/v1/trading/execution/real/market-close-*    404

    The 405 attests the close without sending one. The DEMO strings are
    byte-identical to what the adapter built before this change, so the demo
    environment carries no behavioural risk here — only the real one moves.
    """

    def test_real_omits_the_segment_where_etoro_omits_it(self):
        demo, _ = _client([])
        live, _ = _client([], env="live")
        self.assertEqual(demo._v1_info("portfolio"),
                         f"{BASE}/api/v1/trading/info/demo/portfolio")
        self.assertEqual(live._v1_info("portfolio"),
                         f"{BASE}/api/v1/trading/info/portfolio")
        self.assertEqual(demo._v1_info("aggregate-portfolio"),
                         f"{BASE}/api/v1/trading/info/demo/aggregate-portfolio")
        self.assertEqual(live._v1_info("aggregate-portfolio"),
                         f"{BASE}/api/v1/trading/info/aggregate-portfolio")

    def test_real_writes_the_segment_where_etoro_writes_it(self):
        """/info/real/pnl answered 200 and /info/pnl answered 404. A blanket
        "real omits it" rule would have been right twice and silently wrong
        here — the same class of bug as the one being fixed."""
        live, _ = _client([], env="live")
        self.assertEqual(live._v1_info("pnl"),
                         f"{BASE}/api/v1/trading/info/real/pnl")

    def test_the_close_path_is_the_one_that_answered_405(self):
        """The most expensive URL in the adapter. Order placement is v2 and
        was always right, so a wrong close meant a venue that takes a real
        position and refuses every exit."""
        demo, _ = _client([])
        live, _ = _client([], env="live")
        tail = "market-close-orders/positions/77"
        self.assertEqual(
            live._v1_exec(tail),
            f"{BASE}/api/v1/trading/execution/market-close-orders/positions/77")
        self.assertEqual(
            demo._v1_exec(tail),
            f"{BASE}/api/v1/trading/execution/demo/"
            f"market-close-orders/positions/77")

    def test_an_unattested_tail_raises_instead_of_composing_a_url(self):
        """The guard against repeating this bug. A tail nobody measured is
        "could not ask", not "probably omits it"."""
        live, _ = _client([], env="live")
        with self.assertRaises(LookupError) as caught:
            live._v1_info("watchlists")
        self.assertIn("not attested", str(caught.exception))
        with self.assertRaises(LookupError):
            live._v1_exec("limit-orders")

    def test_demo_needs_no_attestation_because_demo_writes_it_always(self):
        """Demo was never wrong, and must not start raising."""
        demo, _ = _client([])
        self.assertEqual(demo._v1_info("anything-at-all"),
                         f"{BASE}/api/v1/trading/info/demo/anything-at-all")

    def test_no_real_segment_survives_on_a_live_client(self):
        """Except pnl, which eToro genuinely wants it for."""
        live, _ = _client([], env="live")
        for url in (live._v1_info("portfolio"),
                    live._v1_info("aggregate-portfolio"),
                    live._v1_exec("market-close-orders/positions/1"),
                    live._v2("positions/1"), live._v2_exec_orders(),
                    live._v2_lookup()):
            self.assertNotIn("/real/", url, url)

    def test_v2_omits_the_segment_for_real(self):
        demo, _ = _client([])
        live, _ = _client([], env="live")
        self.assertEqual(demo._v2_exec_orders(),
                         f"{BASE}/api/v2/trading/execution/demo/orders")
        self.assertEqual(live._v2_exec_orders(),
                         f"{BASE}/api/v2/trading/execution/orders")
        self.assertEqual(demo._v2_lookup(),
                         f"{BASE}/api/v2/trading/info/demo/orders:lookup")
        self.assertEqual(live._v2_lookup(),
                         f"{BASE}/api/v2/trading/info/orders:lookup")
        self.assertEqual(demo._v2("positions/9"),
                         f"{BASE}/api/v2/trading/demo/positions/9")
        self.assertEqual(live._v2("positions/9"),
                         f"{BASE}/api/v2/trading/positions/9")

    def test_market_data_carries_no_environment(self):
        t, fake = _client([SEARCH_AAPL])
        t.instrument_id("AAPL")
        url = fake.calls[0][1]
        self.assertIn("/api/v1/market-data/search", url)
        self.assertNotIn("/demo", url)
        self.assertNotIn("/real", url)


class TheInstrumentIdIsResolvedOnceTests(SimpleTestCase):

    def test_resolved_via_search_and_cached(self):
        t, fake = _client([SEARCH_AAPL])
        self.assertEqual(t.instrument_id("AAPL"), 1001)
        self.assertEqual(t.instrument_id("aapl"), 1001)
        searches = [c for c in fake.calls if "/search" in c[1]]
        self.assertEqual(len(searches), 1, "the id was fetched twice; "
                                            "it is immutable and cached")
        self.assertEqual(searches[0][2]["params"],
                         {"internalSymbolFull": "AAPL"})

    def test_an_unknown_spelling_raises_rather_than_going_quiet(self):
        """An id of 0 would make every later call answer an empty list,
        which reads as 'no history' — a blind bot, one spelling at a
        time. That is the failure bot_bars.py documents; it stops here."""
        t, _ = _client([("GET", "/search", 200, [])])
        with self.assertRaises(LookupError):
            t.instrument_id("NOPE")

    def test_a_lone_result_of_any_spelling_is_accepted_and_kept(self):
        """instrument_id accepts a single /search item whatever it is
        spelled — a conscious act, pinned here rather than hidden. The
        venue's own spelling is kept beside the id so a reader
        (etoro_smoke) can show the mismatch instead of painting the id
        green. Whether eToro's search is exact or prefix is unmeasured."""
        t, _ = _client([("GET", "/search", 200,
                         [{"instrumentId": 1004,
                           "internalSymbolFull": "SLVX"}])])
        self.assertEqual(t.instrument_id("SLV"), 1004)
        self.assertEqual(t._venue_spelling[1004], "SLVX")
        self.assertEqual(t._symbols[1004], "SLV")

    def test_the_reverse_cache_names_positions_it_opened(self):
        t, _ = _client([SEARCH_AAPL])
        t.instrument_id("AAPL")
        self.assertEqual(t._symbol_for(1001), "AAPL")
        self.assertEqual(t._symbol_for(4242), "ETORO:4242",
                         "a cold id was guessed at instead of reported")


class MarketDataTests(SimpleTestCase):

    def test_klines_map_the_interval_and_return_eleven_columns(self):
        # THE MEASURED SHAPE (2026-09-23, real key, GLDM FourHours 5): one
        # group per instrument, the bars one level down. Before this was
        # measured the adapter read the group as a bar and answered one row
        # with close "0" for every symbol.
        candles = {"candles": [{
            "instrumentId": 1001, "rangeOpen": 1, "rangeHigh": 3,
            "rangeLow": 0.5, "rangeClose": 2, "volume": 106,
            "candles": [
                {"instrumentID": 1001, "fromDate": "2026-09-17T08:00:00Z",
                 "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 99},
                {"instrumentID": 1001, "fromDate": "2026-09-17T12:00:00Z",
                 "open": 1.5, "high": 3, "low": 1, "close": 2, "volume": 7},
            ]}], "interval": "FourHours"}
        t, fake = _client([SEARCH_AAPL,
                           ("GET", "/history/candles", 200, candles)])
        rows = t.klines("AAPL", interval="4h", limit=5000)
        url = [c for c in fake.calls if "/candles" in c[1]][0][1]
        self.assertIn("/instruments/1001/history/candles/asc/FourHours/1000",
                      url, "interval enum, direction or the 1000 cap is "
                           "wrong")
        self.assertEqual(len(rows), 2)
        # Twelve, Binance parity: [open, o, h, l, c, v, close, quoteVol,
        # trades, takerBase, takerQuote, ignore]. The runner reads only
        # r[1]..r[5]; OANDA's docstring says eleven and its code returns
        # twelve, which is how this assertion was first written wrong.
        self.assertEqual(len(rows[0]), 12)
        self.assertEqual(rows[0][1:6], ["1", "2", "0.5", "1.5", "99"])
        self.assertEqual(rows[0][6] - rows[0][0], 4 * 3600 * 1000,
                         "closeTime is not openTime plus the interval")
        self.assertLess(rows[0][0], rows[1][0], "not oldest-first")

    def test_klines_three_states_of_shape(self):
        """A flat list of bars (the shape believed before the key) is still
        read; a group with an empty inner list is an answer (no bars, so
        bot_bars falls back); a row with neither is unmeasured and RAISES —
        never one row of close "0", which bot_bars refused without falling
        back and left a config on eToro with no bars at all."""
        flat = {"candles": [
            {"fromDate": "2026-09-17T08:00:00Z", "open": 1, "high": 2,
             "low": 0.5, "close": 1.5, "volume": 99}]}
        t, _ = _client([SEARCH_AAPL, ("GET", "/history/candles", 200, flat)])
        self.assertEqual(t.klines("AAPL", interval="4h", limit=5)[0][4], "1.5")

        empty_group = {"candles": [{"instrumentId": 1001, "candles": []}],
                       "interval": "FourHours"}
        t, _ = _client([SEARCH_AAPL,
                        ("GET", "/history/candles", 200, empty_group)])
        self.assertEqual(t.klines("AAPL", interval="4h", limit=5), [])

        group_read_as_a_bar = {"candles": [
            {"instrumentId": 1001, "rangeClose": 2, "volume": 106}]}
        t, _ = _client([SEARCH_AAPL,
                        ("GET", "/history/candles", 200, group_read_as_a_bar)])
        with self.assertRaises(LookupError) as caught:
            t.klines("AAPL", interval="4h", limit=5)
        self.assertIn("1001", str(caught.exception))
        self.assertIn("'candles'", str(caught.exception))

    def test_every_platform_timeframe_has_an_enum(self):
        for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"):
            self.assertIn(tf, INTERVAL_MAP)

    def test_ticker_prefers_the_last_execution_then_the_mid(self):
        t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, {"rates": [
            {"bid": 100.0, "ask": 102.0, "lastExecution": 101.3}]})])
        self.assertEqual(t.ticker("AAPL")["lastPrice"], "101.3")
        t2, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, {"rates": [
            {"bid": 100.0, "ask": 102.0, "lastExecution": 0}]})])
        self.assertEqual(t2.ticker("AAPL")["lastPrice"], "101.0")

    def test_ping_is_the_aggregate_portfolio_answering_200(self):
        t, fake = _client([("GET", "/aggregate-portfolio", 200, {})])
        self.assertTrue(t.ping())
        t2, _ = _client([("GET", "/aggregate-portfolio", 401, {})])
        self.assertFalse(t2.ping())


class AnAcceptanceIsNotAFillTests(SimpleTestCase):
    """Fact 1, pinned three ways."""

    def _order(self, lookup_payloads, side="BUY", **kw):
        routes = [SEARCH_AAPL,
                  ("POST", "/execution/demo/orders", 200,
                   {"orderId": 777, "referenceId": "ref-1"})]
        t, fake = _client(routes)
        answers = list(lookup_payloads)

        def hit(method, url, **k):
            fake.calls.append((method, url, k))
            if "orders:lookup" in url:
                return _Resp(200, answers.pop(0) if len(answers) > 1
                             else answers[0])
            for m, sub, status, payload in fake.routes:
                if m == method and sub in url:
                    return _Resp(status, payload)
            return _Resp(200, {})

        fake._hit = hit
        with mock.patch("time.sleep"):
            out = t.market_order("AAPL", side, 10, stop_loss=180,
                                 take_profit=210, **kw)
        return out, fake

    def test_a_filled_order_reports_the_broker_fill_and_the_handle(self):
        out, fake = self._order([_lookup(3)])
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["executedQty"], "10.0")
        self.assertEqual(out["avgPrice"], "190.5")
        self.assertEqual(out["orderId"], "777")
        self.assertTrue(out["protectedOnFill"])
        self.assertEqual(out["protectiveOrders"], [])
        self.assertEqual(out["protectiveTradeId"], "555",
                         "the position id is the handle for moving the "
                         "stop later and is offered exactly once, here")
        post = [c for c in fake.calls if c[0] == "POST"][0]
        body = post[2]["json"]
        self.assertEqual(body["transaction"], "buy")
        self.assertEqual(body["stopLossRate"], 180.0)
        self.assertEqual(body["takeProfitRate"], 210.0)
        self.assertEqual(body["stopLossType"], "fixed")
        self.assertEqual(body["leverage"], 1)
        lookup = [c for c in fake.calls if "orders:lookup" in c[1]][0]
        self.assertEqual(lookup[2]["params"], {"referenceId": "ref-1"},
                         "the fill was not looked up by the reference the "
                         "acceptance echoed back")

    def test_sell_is_sell_short(self):
        out, fake = self._order([_lookup(3)], side="SELL")
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["transaction"], "sellShort")

    def test_a_rejected_order_reports_no_quantity_and_no_protection(self):
        out, _ = self._order([_lookup(4, units=0, avg=0)])
        self.assertEqual(out["status"], "REJECTED")
        self.assertEqual(out["executedQty"], "0.0")
        self.assertNotIn("protectedOnFill", out)

    def test_still_pending_after_polling_is_pending_not_a_fill(self):
        """Five polls, all 'Placed'. The acceptance said 200. The engine
        must receive nothing it could book."""
        out, fake = self._order([{"status": 2}])
        self.assertEqual(out["status"], "PENDING")
        self.assertEqual(out["executedQty"], "0.0")
        self.assertEqual(out["avgPrice"], "0.0")
        self.assertNotIn("protectedOnFill", out)
        polls = [c for c in fake.calls if "orders:lookup" in c[1]]
        self.assertEqual(len(polls), 5, "polling is bounded at five")

    def test_still_pending_is_reported_working_not_booked(self):
        """The engine books an ORDER on this flag, not a position at the
        pre-order ticker (the row reconcile then orphan-closed)."""
        out, _ = self._order([{"status": 2}])
        self.assertIs(out["working"], True)

    def test_waiting_for_market_is_working_too(self):
        out, _ = self._order([{"status": 11}])
        self.assertIs(out["working"], True)
        self.assertEqual(out["executedQty"], "0.0")

    def test_an_unreadable_poll_is_working_never_a_fill(self):
        """Three states: five polls that could not be read are "could not
        ask" — reported working (loud, never CLOSED), never booked."""
        out, _ = self._order([{}])
        self.assertIs(out["working"], True)
        self.assertEqual(out["status"], "PENDING")

    def test_a_fill_and_a_refusal_are_not_working(self):
        out, _ = self._order([_lookup(3)])
        self.assertNotIn("working", out)
        out, _ = self._order([_lookup(4, units=0, avg=0)])
        self.assertNotIn("working", out)

    def test_the_tier_it_cannot_fill_stays_absent(self):
        """`working` is a report; order_status/cancel_order would be
        claims. They stay absent until orders:lookup has met a real key
        under an id this platform persists."""
        self.assertFalse(hasattr(EtoroTrader, "order_status"))
        self.assertFalse(hasattr(EtoroTrader, "cancel_order"))

    def test_polling_stops_early_on_a_terminal_status(self):
        out, fake = self._order([{"status": 2}, _lookup(3)])
        self.assertEqual(out["status"], "FILLED")
        polls = [c for c in fake.calls if "orders:lookup" in c[1]]
        self.assertEqual(len(polls), 2)

    def test_the_status_table_is_the_documented_one(self):
        self.assertEqual(STATUS_FILLED, {3, 5})
        self.assertEqual(set(STATUS_REFUSED), {4, 7, 8, 9, 10})
        for name in STATUS_REFUSED.values():
            self.assertIn(name, ("REJECTED", "CANCELLED", "EXPIRED"),
                          "a refusal word asset_engine does not refuse on")


class TheBracketMoversTests(SimpleTestCase):

    def test_modify_protective_sends_only_the_stop(self):
        t, fake = _client([("PATCH", "/positions/555", 202, {})])
        res = t.modify_protective("555", 185.0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["price"], 185.0)
        body = fake.calls[0][2]["json"]
        self.assertEqual(body, {"stopLossRate": 185.0},
                         "a stop move touched the target — the bug the two "
                         "separate movers exist to prevent")

    def test_modify_target_sends_only_the_target(self):
        t, fake = _client([("PATCH", "/positions/555", 202, {})])
        res = t.modify_target("555", 215.0)
        self.assertTrue(res["ok"])
        self.assertEqual(fake.calls[0][2]["json"], {"takeProfitRate": 215.0})

    def test_a_refusal_is_ok_false_with_no_price(self):
        t, _ = _client([("PATCH", "/positions/555", 400, {"error": "x"})])
        res = t.modify_protective("555", 185.0)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["price"])
        self.assertIn("400", res["reason"])


class TheAccountReadsTests(SimpleTestCase):

    def test_net_liquidation_is_total_value_with_its_currency(self):
        """The payload shape here is the one eToro actually returns, measured
        2026-09-22 against a live real account. It used to be flat — every
        figure at the top level — which is what the adapter looked for and
        what eToro does not send. The URLs were fixed first and the sync
        still wrote no equity; this is the second layer."""
        t, _ = _client([("GET", "/aggregate-portfolio", 200,
                         {"accountCurrency": "EUR",
                          "accountTotals": {"accountTotalValue": 2012.02,
                                            "accountAvailableCash": 400.0}})])
        self.assertEqual(t.net_liquidation(), (2012.02, "EUR"))
        t2, _ = _client([("GET", "/aggregate-portfolio", 200,
                          {"accountCurrency": "EUR",
                           "accountTotals": {"accountTotalValue": 2012.02,
                                             "accountAvailableCash": 400.0}})])
        self.assertEqual(t2.balance_usdt(), 400.0)

    def test_net_liquidation_is_none_when_unreadable_never_zero(self):
        t, _ = _client([("GET", "/aggregate-portfolio", 200, {})])
        self.assertIsNone(t.net_liquidation())
        t2, _ = _client([("GET", "/aggregate-portfolio", 500, {})])
        self.assertIsNone(t2.net_liquidation())

    def test_get_positions_maps_direction_and_raises_on_transport(self):
        t, _ = _client([SEARCH_AAPL, ("GET", "/portfolio", 200, {
            "positions": [
                {"positionID": 1, "instrumentID": 1001, "isBuy": True,
                 "units": 10, "openRate": 190.5},
                {"positionID": 2, "instrumentID": 4242, "isBuy": False,
                 "units": 3, "openRate": 50},
                {"positionID": 3, "instrumentID": 1001, "isBuy": True,
                 "units": 0},
            ]})])
        t.instrument_id("AAPL")
        rows = t.get_positions()
        self.assertEqual(len(rows), 2, "a zero-unit row was reported")
        self.assertEqual(rows[0], {"symbol": "AAPL", "qty": 10.0,
                                   "side": "BUY", "position_id": "1"})
        self.assertEqual(rows[1]["symbol"], "ETORO:4242")
        self.assertEqual(rows[1]["side"], "SELL")
        t2, _ = _client([("GET", "/portfolio", 503, {})])
        with self.assertRaises(RuntimeError):
            t2.get_positions()

    def test_broker_portfolio_is_none_when_unreadable(self):
        t, _ = _client([("GET", "/portfolio", 503, {})])
        self.assertIsNone(t.broker_portfolio())


class WhatItClaimsIsWhatItHasTests(SimpleTestCase):

    def test_the_derived_tiers_are_the_four_intended(self):
        self.assertEqual(cap.capabilities_of(EtoroTrader),
                         ("market_data", "execution", "brackets", "account"))

    def test_orders_and_fills_are_absent_by_design(self):
        """No documented cancel for a pending order; no documented closed-
        position history. A method that existed and could not act would
        pass the conformance test and lie."""
        self.assertFalse(hasattr(EtoroTrader, "cancel_order"))
        self.assertFalse(hasattr(EtoroTrader, "closing_fill"))
        self.assertTrue(hasattr(EtoroTrader, "get_positions"),
                        "reconciliation needs get_positions even without "
                        "the full orders tier")


class TheTotalsAreNestedTests(SimpleTestCase):
    """MEASURED 2026-09-22 against the operator's live real account.

    The path fix made every URL answer 200 and the sync still wrote no
    equity: the field names were wrong too. `account()` puts accountCurrency
    at the TOP level and every figure one level down under `accountTotals`.
    The adapter read the first two at the top and found neither.

    Key names only were read into the session; no amounts. The shape below is
    what eToro returned:

        account()      -> accountCurrency, accountTotals, cid,
                          instrumentAggregates, mirrors, timestamp
        accountTotals  -> accountAvailableCash, accountBalance,
                          accountCurrentPnl, accountFrozenCash,
                          accountTotalUsedMargin, accountTotalValue
    """

    REAL = {
        "accountCurrency": "USD",
        "accountTotals": {
            "accountTotalValue": 1234.56,
            "accountAvailableCash": 1000.0,
            "accountBalance": 1200.0,
            "accountCurrentPnl": 0,
            "accountFrozenCash": 0,
            "accountTotalUsedMargin": 0,
        },
        "cid": 1, "instrumentAggregates": [], "mirrors": [], "timestamp": "t",
    }

    def _t(self, payload):
        from bot_program.engine.etoro_client import EtoroTrader
        t = EtoroTrader("k", "u", env="live")
        t.account = lambda: payload
        return t

    def test_the_total_comes_from_the_nested_block(self):
        self.assertEqual(self._t(self.REAL).net_liquidation(),
                         (1234.56, "USD"))

    def test_the_currency_comes_from_the_top_level(self):
        """eToro really does put it there, and that read was always right."""
        payload = dict(self.REAL)
        payload["accountTotals"] = dict(self.REAL["accountTotals"])
        payload["accountTotals"]["accountCurrency"] = "WRONG"
        self.assertEqual(self._t(payload).net_liquidation()[1], "USD")

    def test_the_cash_comes_from_the_nested_block(self):
        self.assertEqual(self._t(self.REAL).balance_usdt(), 1000.0)

    def test_the_old_top_level_shape_is_unmeasured_not_zero(self):
        """What the adapter used to look for. A payload shaped the old way
        must not be read as a funded account."""
        self.assertIsNone(self._t({"accountTotalValue": 99.0,
                                   "accountCurrency": "USD"}).net_liquidation())

    def test_a_payload_without_the_block_is_unmeasured(self):
        self.assertIsNone(self._t({"accountCurrency": "USD"}).net_liquidation())
        self.assertIsNone(self._t({}).net_liquidation())

    def test_a_non_dict_totals_block_does_not_raise(self):
        self.assertIsNone(
            self._t({"accountTotals": [], "accountCurrency": "USD"})
            .net_liquidation())

    def test_a_zero_account_reads_unmeasured_as_saxo_does(self):
        """Not eToro's peculiarity: SaxoTrader has the identical rule and
        capital_truth states the reasoning — a zero from a live broker cannot
        be told from an API answering badly. Pinned so that changing it here
        alone is a deliberate act, not a drift."""
        payload = dict(self.REAL)
        payload["accountTotals"] = dict(self.REAL["accountTotals"],
                                        accountTotalValue=0.0)
        self.assertIsNone(self._t(payload).net_liquidation())


class TheNoRateAnswerTests(SimpleTestCase):
    """THREE STATES for a tick, and the middle one is the platform's own.

    ibkr_client, oanda_client, paper_trader and public_feed all answer a
    missing rate with the literal {"lastPrice": "0", "symbol": ...}, and
    every reader tests `> 0` and skips — base._mark_price, propose_entry
    ("ticker returned 0"), manual_trade._mark_for, pending_closes,
    reconcile_asset, kill_switch. eToro's empty 200 is that sentinel. A 200
    WITHOUT a `rates` list, or a rate row spelled with none of
    bid/ask/lastExecution, is not: the rates endpoint has never met a real
    key, and a wrong key read as an empty list — or as `.get(...) or 0` —
    is a quiet market forever.
    """

    def test_an_empty_rates_list_is_the_platform_zero_and_is_said(self):
        t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, {"rates": []})])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="INFO") as logs:
            out = t.ticker("AAPL")
        self.assertEqual(out, {"lastPrice": "0", "symbol": "AAPL"})
        self.assertTrue(any("AAPL" in line and "1001" in line
                            for line in logs.output),
                        "the empty answer was not said with its id")

    def test_a_null_rates_value_is_still_the_venue_answering(self):
        t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, {"rates": None})])
        self.assertEqual(t.ticker("AAPL")["lastPrice"], "0")

    def test_a_row_whose_believed_keys_are_all_empty_is_the_venue_zero(self):
        """The row CARRIES bid/ask/lastExecution and they are 0/None: the
        venue answered, and the answer is the same one-spelling sentinel
        the empty list gives — "0", never the "0.0" str(0.0) used to
        return here — with the same INFO line."""
        t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, {"rates": [
            {"bid": 0, "ask": 0, "lastExecution": None}]})])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="INFO") as logs:
            out = t.ticker("AAPL")
        self.assertEqual(out, {"lastPrice": "0", "symbol": "AAPL"})
        self.assertTrue(any("AAPL" in line and "1001" in line
                            for line in logs.output))

    def test_a_payload_without_a_rates_list_raises_naming_what_came_back(self):
        """Not a quiet market: an unmeasured shape. The same rule as `_seg`
        for an unattested tail and instrument_id for a spelling. `{}` is
        what _Resp hands back for a None payload, so it is covered too; a
        `rates` that is present but not a list is the fourth shape."""
        for payload in ({}, {"instrumentRates": []}, [], {"rates": {"bid": 1}}):
            t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, payload)])
            with self.subTest(payload=payload):
                with self.assertRaises(LookupError) as caught:
                    t.ticker("AAPL")
                self.assertIn("'rates'", str(caught.exception))
                self.assertIn("1001", str(caught.exception))

    def test_a_rate_row_spelled_any_other_way_raises_naming_the_row(self):
        """The same rule one level down. The per-rate keys are a belief
        too; a row without any of them used to read `.get(...) or 0` as
        0.0 with no line at all — indistinguishable from a shut market."""
        for row in ({"instrumentId": 1001, "bidRate": 1.0},
                    {"bidPrice": 1, "askPrice": 2}, {}, "x"):
            t, _ = _client([SEARCH_AAPL,
                            ("GET", "/rates", 200, {"rates": [row]})])
            with self.subTest(row=row):
                with self.assertRaises(LookupError) as caught:
                    t.ticker("AAPL")
                self.assertIn("bid/ask/lastExecution", str(caught.exception))
                self.assertIn("1001", str(caught.exception))

    def test_the_sentinel_reaches_the_real_readers_as_no_mark(self):
        """The CONSUMERS, not this file: pending_closes and the bot's own
        _mark_price fed the eToro dict through the real adapter class."""
        from types import SimpleNamespace

        from bot_program.asset_engine.base import AssetBot
        from bot_program.pending_closes import _mark_price, mark_with_quality

        t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 200, {"rates": []})])
        trade = SimpleNamespace(asset_class="stock", symbol="AAPL")
        self.assertIsNone(_mark_price(trade, t))
        self.assertEqual(mark_with_quality(trade, t), (None, {}))
        self.assertIsNone(AssetBot._mark_price(None, trade, t))

    def test_a_transport_error_still_raises(self):
        t, _ = _client([SEARCH_AAPL, ("GET", "/rates", 503, {})])
        with self.assertRaises(RuntimeError):
            t.ticker("AAPL")


class AnUnprotectedOrderIsNeverSentSilentlyTests(SimpleTestCase):
    """`if stop_loss:` dropped a 0.0 leg and SENT a negative one. A caller
    that asked for protection gets the leg or a refusal that says why —
    before any POST, as ValueError, which execute_entry books as
    ORDER_ERROR and manual_trade returns in its error dict."""

    def _routes(self):
        return [SEARCH_AAPL,
                ("POST", "/execution/demo/orders", 200,
                 {"orderId": 777, "referenceId": "ref-1"}),
                ("GET", "orders:lookup", 200, _lookup(3))]

    def _refused(self, **levels):
        t, fake = _client(self._routes())
        with mock.patch("time.sleep"):
            with self.assertRaises(ValueError) as caught:
                t.market_order("AAPL", "BUY", 10, **levels)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [],
                         "the order was POSTed despite the refusal")
        return str(caught.exception)

    def test_a_zero_stop_is_refused_before_the_post(self):
        msg = self._refused(stop_loss=0.0, take_profit=210)
        self.assertIn("NOT SENT", msg[:88],
                      "the fact is past the 88 characters why_no_trade prints")
        self.assertIn("stop_loss", msg[:88])
        self.assertIn("AAPL BUY", msg)

    def test_a_zero_target_is_refused_too(self):
        msg = self._refused(stop_loss=180, take_profit=0)
        self.assertIn("take_profit", msg[:88])

    def test_a_negative_nan_inf_or_non_number_level_is_refused(self):
        for bad in (-5, float("nan"), float("inf"), "abc", True):
            with self.subTest(bad=bad):
                self._refused(stop_loss=bad, take_profit=210)

    def test_none_is_no_leg_asked_for_and_the_order_goes(self):
        """A caller that sent no level asked for no leg — its choice, and
        the fill then claims no protection."""
        t, fake = _client(self._routes())
        with mock.patch("time.sleep"):
            out = t.market_order("AAPL", "BUY", 10)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertNotIn("stopLossRate", body)
        self.assertNotIn("takeProfitRate", body)
        self.assertEqual(out["status"], "FILLED")
        self.assertNotIn("protectedOnFill", out,
                         "protection was claimed on an order with no legs")
        self.assertEqual(out["positionId"], "555")

    def test_a_valid_pair_still_rides_the_body_as_floats(self):
        t, fake = _client(self._routes())
        with mock.patch("time.sleep"):
            out = t.market_order("AAPL", "BUY", 10, stop_loss=180,
                                 take_profit=210)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["stopLossRate"], 180.0)
        self.assertEqual(body["takeProfitRate"], 210.0)
        self.assertEqual(body["stopLossType"], "fixed")
        self.assertTrue(out["protectedOnFill"])

    def test_the_engine_books_the_refusal_as_order_error(self):
        """Read out of the consumer, not this file: the raise lands in the
        `except Exception` that follows client.market_order in
        execute_entry, whose non-in-doubt branch is skips.ORDER_ERROR."""
        import inspect
        import textwrap

        from bot_program.asset_engine.base import AssetBot
        src = textwrap.dedent(inspect.getsource(AssetBot.execute_entry))
        after = src.split("client.market_order(", 1)[1]
        self.assertIn("except Exception as e:", after)
        self.assertIn('getattr(e, "in_doubt", False)', after)
        self.assertIn("skips.ORDER_ERROR", after)
