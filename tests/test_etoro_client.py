"""EtoroTrader against a fake wire (2026-09-17; measured shapes 2026-09-23).

A real key met this adapter on the DEMO segment on 2026-09-23 (deploy/
ETORO_DEPARTURE.md §4 D2, D2b-ii): TheMeasuredWireTests below pins every
shape that came back, byte for byte, and the three DEFECTS the first orders
exposed. The older classes pin the three facts about eToro's API that shape
the adapter, read from the public reference:

  1. ORDERS ARE ASYNCHRONOUS. A 200 on POST is an acceptance. The fill is
     read from orders:lookup, keyed by the INTEGER orderId the acceptance
     carries — NOT by the x-request-id this client sends: eToro echoes it
     as referenceId and forgets it (DEFECTS 1/2, measured: 404 for ever).
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

    def delete(self, url, **kw):
        return self._hit("DELETE", url, **kw)


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


# ── MEASURED 2026-09-23, demo segment, the operator's pair (D2: 1 GLDM at
# 1x, order 383454450 → position 3603281458, closed by order 383413813;
# D2b-ii: the same at 2x, order 383458277; position 3603285267 is the PATCH
# target, paired by timing, never asserted). Every literal below was printed
# by the real adapter (deploy/ETORO_DEPARTURE.md §4) unless a comment beside
# it says "not captured". ──────────────────────────────────────────────────
ACCEPTED = {"token": "04037292-2236-4ba7-b164-3dce815b15e5",
            "orderId": 383454450,
            "referenceId": "c03112d0-7e9c-4186-abb9-39027a79aa91"}
SEARCH_GLDM = ("GET", "/market-data/search", 200,
               [{"instrumentId": 3190, "internalSymbolFull": "GLDM"}])
POST_GLDM = ("POST", "/execution/demo/orders", 200, ACCEPTED)
LOOKUP_404_BY_REFERENCE = (404, {"message": "No external operation was found "
                                 "for referenceId c03112d0-7e9c-4186-abb9-"
                                 "39027a79aa91"})


def _measured_lookup(state="open", *, order_id=383454450, leverage=1,
                     units=1.0, avg=84.8, margin=84.8, exposure=84.8,
                     margin_asset=84.8, exposure_asset=84.8,
                     requested=84.8, frozen=84.93, markup=0.2, stop=82.22,
                     target=87.3, position_id=3603281458):
    """The 200 body of orders:lookup?orderId= (D2, 1x). state "open" right
    after the fill; after the close it is byte-identical but for state
    "closed" — remainingUnits STAYS 1.0. The 2x order differed in exactly
    the printed delta list: leverage 2, requested 42.4, frozen 42.53,
    margin 42.39, exposure 84.79, avg 84.79, markup 0.01.
    marginAssetCurrency / initialExposureAssetCurrency at 2x were not in
    the printed delta list and are not varied here (the 2x fixture leaves
    them at the 1x literal; no test asserts on either). `units` is 1.0 on
    the wire; the engine test sets it to the candidate's size."""
    return {
        "accountId": 15153738, "gcid": 13883661, "portfolioId": 0,
        "orderId": order_id, "action": "open", "transaction": "buy",
        "type": "mkt", "etoroOrderTypeId": 18,
        "status": {"id": 3, "name": "Filled", "errorCode": 0},
        "asset": {"symbol": "GLDM", "instrumentId": 3190, "currency": "USD",
                  "settlementType": "CFD", "leverage": leverage,
                  "side": "long"},
        "orderCurrency": "usd", "requestedAmount": requested,
        "requestedUnits": units, "requestedContracts": units,
        "frozenAmount": frozen, "openStopLossRate": stop,
        "openTakeProfitRate": target, "stopLossType": "fixed",
        "totalCosts": 0.13, "positionsToClose": [],
        "positionExecutions": [{
            "positionId": position_id, "state": state,
            "investedAmountCurrency": 1,
            "initialExposureAccountCurrency": exposure,
            "initialExposureAssetCurrency": exposure_asset, "addedFunds": 0.0,
            "marginAccountCurrency": margin, "marginAssetCurrency": margin_asset,
            "remainingUnits": units, "remainingContracts": units,
            "stopLossRate": stop, "takeProfitRate": target,
            "openingData": {
                "openTime": "2026-09-23T14:06:31.263Z", "orderId": order_id,
                "executionTime": "2026-09-23T14:06:31.463Z",
                "units": units, "contracts": units, "avgPrice": avg,
                "avgConversionRate": 1.0, "marketSpread": 0.01,
                "markup": markup, "priceId": 0, "fees": 0.13,
                "taxes": 0.0}}],
        "requestTime": "2026-09-23T14:06:31.263Z",
        "lastUpdate": "2026-09-23T14:06:31.51Z",
        "openActionType": "customer", "requestType": "byUnits",
    }


PORTFOLIO_ROW = {  # /portfolio -> clientPortfolio.positions[0], capital ID
    "positionID": 3603281458, "CID": 15153738,
    "openDateTime": "2026-09-23T14:06:31.463Z", "openRate": 84.8,
    "instrumentID": 3190, "isBuy": True, "takeProfitRate": 87.3,
    "stopLossRate": 82.22, "mirrorID": 0, "parentPositionID": 0,
    "amount": 84.8, "leverage": 1, "orderID": 383454450, "orderType": 18,
    "units": 1.0, "totalFees": 0.0, "initialAmountInDollars": 84.8,
    "isTslEnabled": False, "stopLossVersion": 1, "isSettled": False,
    "redeemStatusID": 0, "initialUnits": 1.0, "isPartiallyAltered": False,
    "unitsBaseValueDollars": 84.8, "isDiscounted": False,
    "openPositionActionType": 0, "settlementTypeID": 0, "isDetached": False,
    "openConversionRate": 1.0, "pnlVersion": 0, "totalExternalFees": 0.13,
    "totalExternalTaxes": 0.0, "isNoTakeProfit": False,
    "isNoStopLoss": False, "lotCount": 1.0}

CLOSE_RESPONSE = {  # POST market-close-orders/positions/<positionID>
    "orderForClose": {"positionID": 3603281458, "instrumentID": 3190,
                      "orderID": 383413813, "orderType": 19, "statusID": 1,
                      "CID": 15153738,
                      "openDateTime": "2026-09-23T14:08:12.8681106Z",
                      "lastUpdate": "<not captured>"},
    "token": "80c526cc-<not captured>"}
# lastUpdate and token were printed truncated (measured doc §7): placeholders,
# never asserted.


def _totals(value, cash, used, frozen=0.0):
    """aggregate-portfolio at one of the five measured moments."""
    return {"accountCurrency": "USD",
            "accountTotals": {"accountTotalValue": value,
                              "accountAvailableCash": cash,
                              "accountTotalUsedMargin": used,
                              "accountFrozenCash": frozen}}


MOMENTS = {  # (accountTotalValue, accountAvailableCash, accountTotalUsedMargin)
    "before D2": (332449.10, 332449.10, 0.0),
    "after D2 fill (1x)": (332448.94, 332364.17, 84.8),
    "after D2 close": (332448.87, 332448.87, 0.0),
    "after D2b-ii fill (2x)": (332448.71, 332406.35, 42.39),
    "after D2b-ii close": (332448.59, 332448.59, 0.0),
}


def _lookup_router(fake, *, by_order, by_reference=LOOKUP_404_BY_REFERENCE,
                   by_token=(400, {})):
    """Route orders:lookup by its PARAMS, which _FakeSession cannot (it
    matches the URL substring only, and both polls share it). `by_order`
    is one (status, payload) or a list consumed in order — the last one
    repeats — so the measured 500, 500, 500, 200 sequence of a close can
    be played back."""
    seq = list(by_order) if isinstance(by_order, list) else [by_order]

    def hit(method, url, **k):
        fake.calls.append((method, url, k))
        if "orders:lookup" in url:
            p = k.get("params") or {}
            if "orderId" in p:
                return _Resp(*(seq.pop(0) if len(seq) > 1 else seq[0]))
            if "token" in p:
                return _Resp(*by_token)
            return _Resp(*by_reference)
        for m, sub, status, payload in fake.routes:
            if m == method and sub in url:
                return _Resp(status, payload)
        return _Resp(*fake.default)

    fake._hit = hit
    return fake



# ── D2b-i, MEASURED 2026-09-23 20:29 UTC (demo): the held order and its DELETE ──
def _held_lookup(status_id=11, name="WaitingForMarket"):
    """orders:lookup of order 383459788 while WaitingForMarket: status 11,
    positionExecutions [], the legs NOT shown (openStopLossRate 0.0),
    requestedAmount 42.37, frozenAmount 42.5. Every other key is
    _measured_lookup's literal, not captured on the held body."""
    b = _measured_lookup(order_id=383459788, leverage=2, stop=82.17,
                         target=87.25, requested=42.37, frozen=42.5)
    b["status"] = {"id": status_id, "name": name, "errorCode": 0}
    b["positionExecutions"] = []
    b["openStopLossRate"] = 0.0
    b["openTakeProfitRate"] = 0.0
    b["totalCosts"] = 0.0
    return b


def _rewritten_fill():
    """The SHAPE measured on BTC (N2, 2026-09-23): openStopLossRate stays the
    SENT level, positionExecutions[0].stopLossRate is the HELD one. The
    GLDM levels are composed; GLDM itself was never rewritten."""
    b = _measured_lookup(order_id=383459788, leverage=2, stop=82.17,
                         target=87.25, avg=84.79)
    b["positionExecutions"][0]["stopLossRate"] = 83.06
    return b


REJECTED_720 = {**_held_lookup(4, "Rejected"),
                "status": {"id": 4, "name": "Rejected", "errorCode": 720,
                           "errorMessage": "Error opening position - Initial "
                                           "Leveraged Position Amount is under "
                                           "the minimum defined Leveraged Amount "
                                           "in the system. leveraged "
                                           "InitialPositionAmount: 8.44 "
                                           "MinimumPositionAmount: 10 (Dollars)"}}
HELD_ACCEPTED = {"token": "<not captured>", "orderId": 383459788,
                 "referenceId": "<not captured>"}
POST_HELD = ("POST", "/execution/demo/orders", 200, HELD_ACCEPTED)
CANCELED_LOOKUP = _held_lookup(7, "Canceled")
DELETE_202 = ("DELETE", "/api/v3/trading/execution/demo/orders/383459788", 202,
              {"orderId": 383459788, "referenceId": ""})
LOOKUP_404_NOT_INDEXED = (404, {})                    # body not captured
LOOKUP_404_CLOSE_ID = (404, {"message": "Order category for 383413813 not found"})
HELD_TOTALS = _totals(332448.59, 332406.09, 42.5, frozen=42.5)


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

    def test_a_lone_result_spelled_differently_is_refused_not_adopted(self):
        """FIX 6 (2026-09-26). instrument_id used to accept a single
        /search item whatever it was spelled — /search WHEAT answered
        'WHEAT.FUT' 97 alone on 2026-09-23, and ticker() and market_order()
        never compare spellings. It is refused now: a LookupError of that
        exact type (the smoke's no-such/unknown split reads the type)
        naming both spellings and the id, carrying them as lone_id /
        lone_spelling, and nothing cached — so the next ask asks again."""
        t, fake = _client([("GET", "/search", 200,
                            [{"instrumentId": 1004,
                              "internalSymbolFull": "SLVX"}])])
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("SLV")
        self.assertIs(type(cm.exception), LookupError)
        for part in ("'SLV'", "'SLVX'", "1004", "refused, never adopted"):
            self.assertIn(part, str(cm.exception))
        self.assertEqual(cm.exception.lone_id, 1004)
        self.assertEqual(cm.exception.lone_spelling, "SLVX")
        self.assertEqual((t._ids, t._symbols, t._venue_spelling),
                         ({}, {}, {}))
        with self.assertRaises(LookupError):
            t.instrument_id("SLV")
        self.assertEqual(len([c for c in fake.calls if "/search" in c[1]]),
                         2, "a refused lone result was cached")

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

    def test_a_null_volume_is_zero_not_the_text_none(self):
        """A candle's `"volume": null` came out as "None", which the bar
        writer read as an unreadable bar and skipped, price and all."""
        candles = {"candles": [{"instrumentId": 1001, "candles": [
            {"instrumentID": 1001, "fromDate": "2026-09-29T08:00:00Z",
             "open": 83000, "high": 83900, "low": 82800, "close": 83738.56,
             "volume": None},
            {"instrumentID": 1001, "fromDate": "2026-09-29T12:00:00Z",
             "open": 83738.56, "high": 83800, "low": 83700, "close": 83750}]}],
            "interval": "FourHours"}
        t, _ = _client([SEARCH_AAPL, ("GET", "/history/candles", 200, candles)])
        rows = t.klines("AAPL", interval="4h", limit=2)
        self.assertEqual([r[5] for r in rows], ["0", "0"])
        self.assertEqual(rows[0][4], "83738.56")

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
        # THE DEFAULT, pinned: no `leverage=` kwarg -> the literal 1 this
        # body carried before 2026-09-23. A kwarg changes it (the
        # AnUnprotectedOrderIsNeverSentSilentlyTests below), nothing else.
        self.assertEqual(body["leverage"], 1)
        lookup = [c for c in fake.calls if "orders:lookup" in c[1]][0]
        self.assertEqual(lookup[2]["params"], {"orderId": "777"},
                         "the fill must be looked up by the orderId the "
                         "acceptance carries — a lookup by the echoed "
                         "referenceId answers 404 for ever (measured "
                         "2026-09-23)")

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

    def test_the_tier_it_fills_since_d3b_is_present(self):
        """`working` was a report until the WORKING shape and the DELETE
        met a key (D2b-i, 2026-09-23 20:29 UTC: status 11, DELETE v3 -> 202,
        lookup 7). Since D3b both are claims the adapter can keep, on the
        demo segment, and since 2026-09-26 on the real one (the real DELETE
        measured: 202, then 7 Canceled)."""
        self.assertTrue(hasattr(EtoroTrader, "order_status"))
        self.assertTrue(hasattr(EtoroTrader, "cancel_order"))

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

    def test_broker_portfolio_carries_the_venues_leverage_only_when_the_row_says(self):
        """Public reference (unmeasured): a /portfolio position has a
        `leverage` field. Three states on the way out — the number the row
        carried, or NO key at all; never 1 for a row that did not say."""
        t, _ = _client([SEARCH_AAPL, ("GET", "/portfolio", 200, {
            "positions": [
                {"positionID": 1, "instrumentID": 1001, "isBuy": True,
                 "units": 10, "openRate": 190.5, "leverage": 5},
                {"positionID": 2, "instrumentID": 1001, "isBuy": True,
                 "units": 3, "openRate": 190.5},
                {"positionID": 3, "instrumentID": 1001, "isBuy": True,
                 "units": 3, "openRate": 190.5, "leverage": "x"},
            ]})])
        t.instrument_id("AAPL")
        rows = t.broker_portfolio()
        self.assertEqual(rows[0]["leverage"], 5)
        self.assertNotIn("leverage", rows[1])
        self.assertNotIn("leverage", rows[2])
        self.assertEqual([r["qty"] for r in rows], [10.0, 3.0, 3.0],
                         "units are units at any leverage")

    def test_broker_portfolio_is_none_when_unreadable(self):
        t, _ = _client([("GET", "/portfolio", 503, {})])
        self.assertIsNone(t.broker_portfolio())


class WhatItClaimsIsWhatItHasTests(SimpleTestCase):

    def test_the_derived_tiers_are_the_nine_intended(self):
        """fractional_units joined 2026-09-23 as a labelled belief (measured
        the same night on BTC, and MEASURED per instrument since C1
        2026-09-25); orders joined with D3b off the measured DELETE;
        money_floor, order_caps and leverage_values joined with C1 off the
        eligibility row read on 2026-09-23. Every tier is derived from the
        methods on the class."""
        self.assertEqual(cap.capabilities_of(EtoroTrader),
                         ("market_data", "execution", "orders", "brackets",
                          "account", "fractional_units", "money_floor",
                          "order_caps", "leverage_values"))

    def test_the_module_header_names_every_tier_and_calls_none_a_belief(self):
        """The table at the top of etoro_client.py is read by people, not
        by the engine, so it is pinned here: every tier the class derives
        is named in it (nine since C1, 2026-09-25), every accessor of the
        three eligibility tiers too, and the word BELIEVED is gone (the
        fractional tier is a measurement off unitsQuantityType since C1;
        the header said BELIEVED until the round-2 critic read it)."""
        import bot_program.engine.etoro_client as _ec
        head = (_ec.__doc__ or "").split("WHY THIS BROKER")[0]
        self.assertTrue(head, "the module docstring lost its header")
        for tier in cap.capabilities_of(EtoroTrader):
            self.assertIn(tier, head, tier)
        for name in ("takes_fractional_units", "min_notional",
                     "max_units_per_order", "allow_open_position",
                     "eligibility_state", "leverage_values",
                     "max_stop_loss_pct", "settlement_for"):
            self.assertIn(name, head, name)
        self.assertNotIn("BELIEVED", head)

    def test_fills_is_absent_by_design_and_orders_is_measured(self):
        """No closed-position history is documented, so `fills` stays
        absent; the cancel met a key on 2026-09-23 (DELETE v3 -> 202 ->
        lookup 7), so `orders` is claimed."""
        self.assertTrue(hasattr(EtoroTrader, "cancel_order"))
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

    def test_leverage_above_one_without_a_stop_is_refused_before_the_post(self):
        """Public reference (unmeasured): a stopLossRate is required when
        leverage is greater than 1. Refused HERE, in `_level`'s voice,
        rather than by eToro after the POST — and never sent at 1 instead."""
        msg = self._refused(leverage=2, take_profit=210)
        self.assertIn("NOT SENT", msg[:88])
        self.assertIn("leverage 2", msg[:88])
        self.assertIn("stop_loss", msg[:88])

    def test_a_leverage_that_is_not_a_whole_number_at_least_one_is_refused(self):
        for bad in (0, -1, 1.5, "2", True, float("nan"), float("inf")):
            with self.subTest(bad=bad):
                msg = self._refused(leverage=bad, stop_loss=180,
                                    take_profit=210)
                self.assertIn("leverage", msg[:88])

    def test_leverage_past_the_adapter_ceiling_is_refused_not_clamped(self):
        from bot_program.engine.etoro_client import LEVERAGE_MAX
        msg = self._refused(leverage=LEVERAGE_MAX + 1, stop_loss=180,
                            take_profit=210)
        self.assertIn(str(LEVERAGE_MAX), msg)

    def test_a_leverage_kwarg_rides_the_body_as_that_integer(self):
        t, fake = _client(self._routes())
        with mock.patch("time.sleep"):
            out = t.market_order("AAPL", "BUY", 10, stop_loss=180,
                                 take_profit=210, leverage=2)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["leverage"], 2)
        self.assertIs(type(body["leverage"]), int)
        self.assertEqual(body["units"], 10.0,
                         "leverage changed the units — it must change the "
                         "margin eToro locks and nothing else")
        self.assertNotIn("settlementType", body,
                         "what eToro assigns when the body omits it is "
                         "unmeasured; D2b reads settlementTypeID back")
        self.assertEqual(body["stopLossRate"], 180.0)
        self.assertEqual(out["status"], "FILLED")
        self.assertTrue(out["protectedOnFill"])

    def test_an_explicit_leverage_of_one_is_the_default_body(self):
        t, fake = _client(self._routes())
        with mock.patch("time.sleep"):
            t.market_order("AAPL", "BUY", 10, leverage=1)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["leverage"], 1)
        self.assertNotIn("stopLossRate", body,
                         "at leverage 1 None is still no leg asked for")

    def test_the_venues_stop_echo_rides_out_as_venue_keys(self):
        t, _ = _client(self._routes())
        with mock.patch("time.sleep"):
            out = t.market_order("AAPL", "BUY", 10, stop_loss=180,
                                 take_profit=210)
        self.assertEqual(out["venueStopLoss"], 180.0)
        self.assertEqual(out["venueTakeProfit"], 210.0)
        lk = _lookup(3)
        lk["positionExecutions"][0].pop("stopLossRate")
        lk["positionExecutions"][0].pop("takeProfitRate")
        t2, _ = _client([SEARCH_AAPL,
                         ("POST", "/execution/demo/orders", 200,
                          {"orderId": 777, "referenceId": "ref-1"}),
                         ("GET", "orders:lookup", 200, lk)])
        with mock.patch("time.sleep"):
            out2 = t2.market_order("AAPL", "BUY", 10, stop_loss=180,
                                   take_profit=210)
        self.assertNotIn("venueStopLoss", out2)
        self.assertNotIn("venueTakeProfit", out2)

    def test_a_failed_poll_is_pending_working_and_says_so(self):
        t, _ = _client([SEARCH_AAPL,
                        ("POST", "/execution/demo/orders", 200,
                         {"orderId": 777, "referenceId": "ref-1"}),
                        ("GET", "orders:lookup", 503, {})])
        with mock.patch("time.sleep"):
            out = t.market_order("AAPL", "BUY", 10, stop_loss=180,
                                 take_profit=210, leverage=2)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out["working"])
        self.assertTrue(out["pollFailed"])
        t2, _ = _client([SEARCH_AAPL,
                         ("POST", "/execution/demo/orders", 200,
                          {"orderId": 777, "referenceId": "ref-1"}),
                         ("GET", "orders:lookup", 200, _lookup(1))])
        with mock.patch("time.sleep"):
            out2 = t2.market_order("AAPL", "BUY", 10, stop_loss=180,
                                   take_profit=210)
        self.assertTrue(out2["working"])
        self.assertNotIn("pollFailed", out2,
                         "a lookup that ANSWERED Received is eToro holding "
                         "it, not a failed poll")

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


# ── the wire as it measured on 2026-09-23 ──────────────────────────────────

def _polls(fake):
    return [c for c in fake.calls if c[0] == "GET" and "orders:lookup" in c[1]]


# ── MEASURED 2026-09-28 22:42 UTC, demo segment, the operator's pair, the
# night before leaving: EURUSD 1000 units BUY twice the same minute, at 1x
# (order 384690781 → position 3605812674, closed by order 384732103) and at
# 5x (order 384647176 → position 3605812677, closed by order 384726349).
# Every literal below was printed by the real adapter through the shell
# snippet of that sitting (the session's transcript) unless a comment says
# "not captured". The acceptance bodies were not printed raw (the adapter
# printed the orderId it read off them): composed with the measured int.
# eToro's REAL id for EURUSD is 1 (printed by instrument_id that night);
# SEARCH_EURUSD further down carries the fixture id 1002 of the leverage
# tests and stays theirs.
SEARCH_EURUSD_MEASURED = ("GET", "/market-data/search", 200,
                          [{"instrumentId": 1,
                            "internalSymbolFull": "EURUSD"}])
FX_ACCEPTED_1X = {"token": "<not captured>", "orderId": 384690781,
                  "referenceId": "<not captured>"}
FX_ACCEPTED_5X = {"token": "<not captured>", "orderId": 384647176,
                  "referenceId": "<not captured>"}


def _fx_lookup(state="open", *, leverage=1):
    """orders:lookup?orderId= (demo segment) of the two EURUSD orders,
    verbatim. At 1x eToro REWROTE the stop: sent 1.13146 (0.5% under the
    last 1.13715, kept on the top level as openStopLossRate), held 1.12579
    on positionExecutions[0] (1% under the fill 1.13716); at 5x the sent
    stop was held. requestedAmount is the notional at 1x (1137.16, all of
    it locked as margin) and notional / 5 at 5x (227.43; margin 227.42).
    fees 0.0 on forex, markup 0.03 at 1x / 0.04 at 5x, marketSpread 0.01.
    After the close the body is the same but for state "closed"."""
    one = leverage == 1
    return {
        "accountId": 15153738, "gcid": 13883661, "portfolioId": 0,
        "orderId": 384690781 if one else 384647176, "action": "open",
        "transaction": "buy", "type": "mkt", "etoroOrderTypeId": 18,
        "status": {"id": 3, "name": "Filled", "errorCode": 0},
        "asset": {"symbol": "EURUSD", "instrumentId": 1, "currency": "USD",
                  "settlementType": "CFD", "leverage": leverage,
                  "side": "long"},
        "orderCurrency": "usd",
        "requestedAmount": 1137.16 if one else 227.43,
        "requestedUnits": 1000.0, "requestedContracts": 1.0,
        "frozenAmount": 1137.16 if one else 227.43,
        "openStopLossRate": 1.13146, "openTakeProfitRate": 1.14284,
        "stopLossType": "fixed", "totalCosts": 0.0, "positionsToClose": [],
        "positionExecutions": [{
            "positionId": 3605812674 if one else 3605812677, "state": state,
            "investedAmountCurrency": 1,
            "initialExposureAccountCurrency": 1137.16,
            "initialExposureAssetCurrency": 1137.16, "addedFunds": 0.0,
            "marginAccountCurrency": 1137.16 if one else 227.42,
            "marginAssetCurrency": 1137.16 if one else 227.42,
            "remainingUnits": 1000.0, "remainingContracts": 1.0,
            "stopLossRate": 1.12579 if one else 1.13146,
            "takeProfitRate": 1.14284,
            "openingData": {
                "openTime": ("2026-09-28T22:42:46.363Z" if one
                             else "2026-09-28T22:42:55.877Z"),
                "orderId": 384690781 if one else 384647176,
                "executionTime": ("2026-09-28T22:42:46.467Z" if one
                                  else "2026-09-28T22:42:56Z"),
                "units": 1000.0, "contracts": 1.0, "avgPrice": 1.13716,
                "avgConversionRate": 1.0, "marketSpread": 0.01,
                "markup": 0.03 if one else 0.04, "priceId": 0,
                "fees": 0.0, "taxes": 0.0}}],
        "requestTime": ("2026-09-28T22:42:46.42Z" if one
                        else "2026-09-28T22:42:55.947Z"),
        "lastUpdate": ("2026-09-28T22:42:46.517Z" if one
                       else "2026-09-28T22:42:56.047Z"),
        "openActionType": "customer", "requestType": "byUnits",
    }


FX_CLOSE_1X = {"orderForClose": {"positionID": 3605812674, "instrumentID": 1,
                                 "orderID": 384732103, "orderType": 19,
                                 "statusID": 1, "CID": 15153738,
                                 "openDateTime": "2026-09-28T22:42:48.0548543Z",
                                 "lastUpdate": "2026-09-28T22:42:48.0548543Z"},
               "token": "<not asserted>"}
FX_CLOSE_5X = {"orderForClose": {"positionID": 3605812677, "instrumentID": 1,
                                 "orderID": 384726349, "orderType": 19,
                                 "statusID": 1, "CID": 15153738,
                                 "openDateTime": "2026-09-28T22:42:57.2067188Z",
                                 "lastUpdate": "2026-09-28T22:42:57.2067188Z"},
               "token": "<not asserted>"}
# The cells printed after each close: {available_cash, used_margin} —
# the 1x round trip cost 0.01 (332440.16 -> 332440.15), the 5x another 0.01.
FX_CELLS_AFTER_CLOSE_1X = {"accountCurrency": "USD",
                           "accountTotals": {"accountAvailableCash": 332440.15,
                                             "accountTotalUsedMargin": 0.0}}
FX_CELLS_AFTER_CLOSE_5X = {"accountCurrency": "USD",
                           "accountTotals": {"accountAvailableCash": 332440.14,
                                             "accountTotalUsedMargin": 0.0}}


# ── MEASURED 2026-09-29 10:57 UTC, demo segment, the operator's pair (a
# client built env='demo' in the shell, D1's WORLD CHECK first:
# net_liquidation 332440.14 USD; the row itself stayed live, no box moved):
# one BUY at 1x per class, each closed by position id at once, printed by
# the real adapter. The legs sent were the last price x 0.97 / x 1.03 to
# four decimals; eToro HELD them rounded to the instrument's two decimals
# (positionExecutions[0]), the top level keeping the sent value. Every
# close proof met eToro's transient 500 on the way (AAPL twice, SPX500 and
# WHEAT.FUT once) before "closed". /portfolio read [] 60 s after the last.
# The acceptance bodies were not printed raw: composed with the measured
# int orderId, as the forex fixtures are.
CLASS_PROOFS = {
    "stock": {
        "symbol": "AAPL", "venue": "AAPL", "iid": 1001, "units": 4.0,
        "sent": (326.6184, 346.8216), "held": (326.62, 346.82),
        "order": 384798829, "position": 3605938942, "close_order": 384822839,
        "avg": 336.87, "settlement": "REAL", "requested": 1347.52,
        "frozen": 1348.52, "total_costs": 1.0, "margin": 1347.48,
        "exposure": 1347.48, "spread": 0.64, "markup": 0.0, "fees": 1.0,
        "times": ("2026-09-29T10:57:01.907Z", "2026-09-29T10:57:02.05Z",
                  "2026-09-29T10:57:01.997Z", "2026-09-29T10:57:02.093Z",
                  "2026-09-29T10:57:03.3669863Z"),
        "close_500s": 2, "cash_after_open": 331091.66,
        "cash_after_close": 332437.62,
    },
    "index": {
        "symbol": "SPX500", "venue": "SPX500", "iid": 27, "units": 1.0,
        "sent": (7458.5531, 7919.9069), "held": (7458.56, 7919.9),
        "order": 384769149, "position": 3605939058, "close_order": 384793580,
        "avg": 7689.63, "settlement": "CFD", "requested": 7689.63,
        "frozen": 7689.63, "total_costs": 0.0, "margin": 7689.63,
        "exposure": 7689.63, "spread": 0.4, "markup": 0.04, "fees": 0.0,
        "times": ("2026-09-29T10:57:15.853Z", "2026-09-29T10:57:15.963Z",
                  "2026-09-29T10:57:15.92Z", "2026-09-29T10:57:16.013Z",
                  "2026-09-29T10:57:17.3660212Z"),
        "close_500s": 1, "cash_after_open": 324747.99,
        "cash_after_close": 332437.22,
    },
    "commodity": {
        "symbol": "WHEATUSD", "venue": "WHEAT.FUT", "iid": 97, "units": 2.0,
        "sent": (662.995, 704.005), "held": (663.0, 704.0),
        "order": 384769151, "position": 3605939068, "close_order": 384813052,
        "avg": 683.75, "settlement": "CFD", "requested": 1367.5,
        "frozen": 1367.5, "total_costs": 0.0, "margin": 1367.5,
        "exposure": 1367.5, "spread": 0.5, "markup": 0.06, "fees": 0.0,
        "times": ("2026-09-29T10:57:25.66Z", "2026-09-29T10:57:25.793Z",
                  "2026-09-29T10:57:25.743Z", "2026-09-29T10:57:25.853Z",
                  "2026-09-29T10:57:27.3307109Z"),
        "close_500s": 1, "cash_after_open": 331069.72,
        "cash_after_close": 332436.72,
    },
}


# ── MEASURED 2026-09-29 12:02 UTC, the same demo sitting's second pass: one
# FRACTIONAL BUY at 1x per class (deploy/ETORO_DEPARTURE.md §4 D2c-1, at two
# decimals), closed at once by position id. The legs were sent at the last
# price x 0.97 / x 1.03 to two decimals and held as sent. AAPL's and
# WHEAT.FUT's first fill poll answered 404 before the 200 (the lookup not
# yet indexed); the close proofs met one, one and three 500s.
CLASS_FRACTION_PROOFS = {
    "stock": {
        "symbol": "AAPL", "venue": "AAPL", "iid": 1001, "units": 0.05,
        "sent": (327.08, 347.32), "held": (327.08, 347.32),
        "order": 384799082, "position": 3605955721, "close_order": 384842884,
        "avg": 337.21, "settlement": "REAL", "requested": 16.86,
        "frozen": 17.86, "total_costs": 1.0, "margin": 16.86,
        "exposure": 16.8605, "spread": 0.0, "markup": 0.0, "fees": 1.0,
        "times": ("2026-09-29T12:02:23.097Z", "2026-09-29T12:02:23.187Z",
                  "2026-09-29T12:02:23.153Z", "2026-09-29T12:02:23.22Z",
                  "2026-09-29T12:02:25.6696274Z"),
        "fill_404s": 1, "close_500s": 1, "cash_after_close": 332434.74,
    },
    "index": {
        "symbol": "SPX500", "venue": "SPX500", "iid": 27, "units": 0.14,
        "sent": (7473.1, 7935.36), "held": (7473.1, 7935.36),
        "order": 384769398, "position": 3605955732, "close_order": 384823407,
        "avg": 7704.5, "settlement": "CFD", "requested": 1078.63,
        "frozen": 1078.63, "total_costs": 0.0, "margin": 1078.63,
        "exposure": 1078.63, "spread": 0.06, "markup": 0.04, "fees": 0.0,
        "times": ("2026-09-29T12:02:35.82Z", "2026-09-29T12:02:35.907Z",
                  "2026-09-29T12:02:35.867Z", "2026-09-29T12:02:35.97Z",
                  "2026-09-29T12:02:37.2121022Z"),
        "fill_404s": 0, "close_500s": 1, "cash_after_close": 332434.7,
    },
    "commodity": {
        "symbol": "WHEATUSD", "venue": "WHEAT.FUT", "iid": 97, "units": 1.5,
        "sent": (668.09, 709.41), "held": (668.09, 709.41),
        "order": 384799086, "position": 3605955741, "close_order": 384823413,
        "avg": 689.0, "settlement": "CFD", "requested": 1033.5,
        "frozen": 1033.5, "total_costs": 0.0, "margin": 1033.5,
        "exposure": 1033.5, "spread": 0.38, "markup": 3.0, "fees": 0.0,
        "times": ("2026-09-29T12:02:45.37Z", "2026-09-29T12:02:45.503Z",
                  "2026-09-29T12:02:45.45Z", "2026-09-29T12:02:45.547Z",
                  "2026-09-29T12:02:50.8835143Z"),
        "fill_404s": 1, "close_500s": 3, "cash_after_close": 332434.32,
    },
}


# ── MEASURED 2026-10-01 21:02 UTC on the DEMO segment: the first eToro
# SELL that ever filled (the operator: "régler la vente à découvert vite").
# AAPL 4 units at 1x, the stop sent ABOVE and the target BELOW (last 330.01
# x 1.03 / x 0.97, two decimals), held as sent; the fill poll met one 404,
# the close by position id three 500s. The same sitting's SPX500 1 and
# EURUSD 1000 SELLs were REJECTED (errorCode 749, "Error creating entry
# order - disallowed for instrument(27)" / "(1)") at 21:01:38 / 21:01:59,
# New York's 17:00 rollover: pinned in TheShortRejectionTests below.
CLASS_SHORT_PROOFS = {
    "stock": {
        "symbol": "AAPL", "venue": "AAPL", "iid": 1001, "units": 4.0,
        "order_side": "SELL", "transaction": "sell", "side": "short",
        "sent": (339.91, 320.11), "held": (339.91, 320.11),
        "order": 385673365, "position": 3608630747, "close_order": 385717837,
        "avg": 330.01, "settlement": "CFD", "requested": 1320.04,
        "frozen": 1322.02, "total_costs": 1.98, "margin": 1320.04,
        "exposure": 1320.04, "spread": 1.24, "markup": 0.08, "fees": 1.98,
        "times": ("2026-10-01T21:02:19.577Z", "2026-10-01T21:02:19.707Z",
                  "2026-10-01T21:02:19.577Z", "2026-10-01T21:02:19.76Z",
                  "2026-10-01T21:02:22.1944487Z"),
        "fill_404s": 1, "close_500s": 3, "cash_after_open": 331112.3,
        "cash_after_close": 332429.12,
    },
    # MEASURED 2026-10-01 21:17 UTC, the second short sitting: EURUSD 1000
    # SELL at 1x FILLED (the 21:01:59 one was rejected 749 inside New
    # York's 17:00 rollover); SPX500 and NSDQ100 rejected 749 again at 1x
    # and 2x (21:16:53-21:17:05); USDJPY never sent (/search answered 429).
    "forex": {
        "symbol": "EURUSD", "venue": "EURUSD", "iid": 1, "units": 1000.0,
        "order_side": "SELL", "transaction": "sell", "side": "short",
        "sent": (1.1573, 1.08988), "held": (1.1573, 1.08988),
        "order": 385673393, "position": 3608631633, "close_order": 385717862,
        "avg": 1.12453, "settlement": "CFD", "requested": 1124.53,
        "frozen": 1124.53, "total_costs": 0.0, "margin": 1124.53,
        "exposure": 1124.53, "spread": 0.22, "markup": 0.03, "fees": 0.0,
        "times": ("2026-10-01T21:17:11.82Z", "2026-10-01T21:17:11.9Z",
                  "2026-10-01T21:17:11.857Z", "2026-10-01T21:17:11.947Z",
                  "2026-10-01T21:17:13.2111637Z"),
        "fill_404s": 0, "close_500s": 3, "cash_after_open": 331304.59,
        "cash_after_close": 332428.9,
    },
}


def _class_lookup(p, state="open"):
    """orders:lookup?orderId= of one 2026-09-29 class proof, verbatim; after
    the close the same body but for state "closed". A SELL proof
    (CLASS_SHORT_PROOFS) carries its own transaction and side words."""
    open_time, exec_time, req_time, last_update, _close_time = p["times"]
    return {
        "accountId": 15153738, "gcid": 13883661, "portfolioId": 0,
        "orderId": p["order"], "action": "open",
        "transaction": p.get("transaction", "buy"),
        "type": "mkt", "etoroOrderTypeId": 18,
        "status": {"id": 3, "name": "Filled", "errorCode": 0},
        "asset": {"symbol": p["venue"], "instrumentId": p["iid"],
                  "currency": "USD", "settlementType": p["settlement"],
                  "leverage": 1, "side": p.get("side", "long")},
        "orderCurrency": "usd", "requestedAmount": p["requested"],
        "requestedUnits": p["units"], "requestedContracts": p["units"],
        "frozenAmount": p["frozen"], "openStopLossRate": p["sent"][0],
        "openTakeProfitRate": p["sent"][1], "stopLossType": "fixed",
        "totalCosts": p["total_costs"], "positionsToClose": [],
        "positionExecutions": [{
            "positionId": p["position"], "state": state,
            "investedAmountCurrency": 1,
            "initialExposureAccountCurrency": p["exposure"],
            "initialExposureAssetCurrency": p["exposure"], "addedFunds": 0.0,
            "marginAccountCurrency": p["margin"],
            "marginAssetCurrency": p["margin"],
            "remainingUnits": p["units"], "remainingContracts": p["units"],
            "stopLossRate": p["held"][0], "takeProfitRate": p["held"][1],
            "openingData": {
                "openTime": open_time, "orderId": p["order"],
                "executionTime": exec_time, "units": p["units"],
                "contracts": p["units"], "avgPrice": p["avg"],
                "avgConversionRate": 1.0, "marketSpread": p["spread"],
                "markup": p["markup"], "priceId": 0, "fees": p["fees"],
                "taxes": 0.0}}],
        "requestTime": req_time, "lastUpdate": last_update,
        "openActionType": "customer", "requestType": "byUnits",
    }


def _class_close(p):
    return {"orderForClose": {"positionID": p["position"],
                              "instrumentID": p["iid"],
                              "orderID": p["close_order"], "orderType": 19,
                              "statusID": 1, "CID": 15153738,
                              "openDateTime": p["times"][4],
                              "lastUpdate": p["times"][4]},
            "token": "<not asserted>"}


class TheMeasuredWireTests(SimpleTestCase):
    """Every shape the first demo orders printed, pinned byte for byte with
    the real EtoroTrader over a patched session. The three DEFECTS they
    exposed are the regression pins here: the fill poll by referenceId (404
    for ever), the unfindable close order, the lagging /portfolio."""

    def _t(self, by_order, routes=None, **router_kw):
        t, fake = _client(list(routes if routes is not None
                               else [SEARCH_GLDM, POST_GLDM]))
        _lookup_router(fake, by_order=by_order, **router_kw)
        return t, fake

    def _order(self, t, **kw):
        with mock.patch("time.sleep"):
            return t.market_order("GLDM", "BUY", 1, stop_loss=82.22,
                                  take_profit=87.3, **kw)

    def _closer(self, by_order):
        return self._t(by_order, routes=[
            SEARCH_GLDM,
            ("POST", "/market-close-orders/positions/3603281458", 200,
             CLOSE_RESPONSE)])

    def test_proof_etf(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-23 14:06 UTC (deploy/
        ETORO_DEPARTURE.md §4 D2, the operator's own pair on the virtual
        portfolio): GLDM 1 unit BUY at 1x, stop 82.22 / target 87.3 sent.
        FILLED in 200 ms (requestTime .263Z -> executionTime .463Z) —
        order 383454450, position 3603281458, avgPrice 84.8, settlementType
        CFD, fees 0.13, marginAccountCurrency 84.8, both legs held as sent.
        CLOSED by the market-close POST on the position id: orderForClose
        {orderID 383413813, orderType 19, statusID 1}, proven by the OPEN
        order's positionExecutions[0].state turning "closed" — never by
        /portfolio, which lagged (DEFECT 3). The class token is "etf": the
        gate keys on the INSTRUMENT's class and GLDM's row is an ETF, so
        this lifts the ETF entries of the stocks box (config 14) and
        nothing else — "stock" and "index" wait for their own round trip.
        "etf" joins ETORO_PROVEN in the commit that pins this (2026-09-28),
        at 1x only, on the demo proof the plan admits ("on the demo segment
        OR the real account, a real one being the stronger", §7 bullet 0)."""
        t, fake = self._t([(200, _measured_lookup("open")),
                           (200, _measured_lookup("closed"))], routes=[
            SEARCH_GLDM, POST_GLDM,
            ("POST", "/market-close-orders/positions/3603281458", 200,
             CLOSE_RESPONSE)])
        r = self._order(t)
        # the order that went: the demo segment, GLDM, 1 unit, 1x, both legs
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(post[1],
                         f"{BASE}/api/v2/trading/execution/demo/orders")
        body = post[2]["json"]
        self.assertEqual((body["symbol"], float(body["units"]),
                          body["leverage"], body["stopLossRate"],
                          body["takeProfitRate"]),
                         ("GLDM", 1.0, 1, 82.22, 87.3))
        # the fill, read by orderId, off positionExecutions[0]
        polls = _polls(fake)
        self.assertEqual(polls[0][2]["params"], {"orderId": "383454450"})
        self.assertEqual((r["orderId"], r["status"], r["executedQty"],
                          r["avgPrice"], r["positionId"]),
                         ("383454450", "FILLED", "1.0", "84.8",
                          "3603281458"))
        self.assertEqual((r["venueStopLoss"], r["venueTakeProfit"]),
                         (82.22, 87.3))
        lk = r["raw"]["lookup"]
        self.assertEqual((lk["asset"]["settlementType"],
                          lk["asset"]["leverage"], lk["asset"]["symbol"]),
                         ("CFD", 1, "GLDM"))
        first = lk["positionExecutions"][0]
        self.assertEqual((first["openingData"]["fees"],
                          first["marginAccountCurrency"],
                          first["openingData"]["avgPrice"]),
                         (0.13, 84.8, 84.8))
        # the close by position id, proven by the OPEN order
        with mock.patch("time.sleep"):
            c = t.close_position("3603281458", "GLDM",
                                 open_order_id="383454450")
        close_post = [x for x in fake.calls if x[0] == "POST"][1]
        self.assertTrue(close_post[1].endswith(
            "/market-close-orders/positions/3603281458"), close_post[1])
        self.assertEqual(close_post[2]["json"], {"InstrumentID": 3190})
        self.assertEqual((c["status"], c["positionState"], c["orderId"],
                          c["openOrderId"]),
                         ("FILLED", "closed", "383413813", "383454450"))
        self.assertEqual(c["raw"]["orderForClose"],
                         CLOSE_RESPONSE["orderForClose"])
        self.assertNotIn("executedQty", c, "no units asked, none claimed")
        self.assertNotIn("avgPrice", c, "a close carries no price")
        # every write met the DEMO world, never the real one
        for m, url, _k in fake.calls:
            if m == "POST":
                self.assertIn("/demo/", url, url)
                self.assertNotIn("/real/", url, url)

    def _fx_round_trip(self, leverage, accepted, close, cells):
        """The measured EURUSD round trip at `leverage`, through the real
        adapter over the fake wire: the order, the fill, the close proven
        by the open order through the one 500 each close met, the cells."""
        one = leverage == 1
        position = "3605812674" if one else "3605812677"
        t, fake = self._t([(200, _fx_lookup("open", leverage=leverage)),
                           (500, {}),
                           (200, _fx_lookup("closed", leverage=leverage))],
                          routes=[
            SEARCH_EURUSD_MEASURED,
            ("POST", "/execution/demo/orders", 200, accepted),
            ("POST", f"/market-close-orders/positions/{position}", 200,
             close),
            ("GET", "/aggregate-portfolio", 200, cells)])
        with mock.patch("time.sleep"):
            r = t.market_order("EURUSD", "BUY", 1000, stop_loss=1.13146,
                               take_profit=1.14284, leverage=leverage)
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(post[1],
                         f"{BASE}/api/v2/trading/execution/demo/orders")
        body = post[2]["json"]
        self.assertEqual((body["symbol"], float(body["units"]),
                          body["leverage"], body["stopLossRate"],
                          body["takeProfitRate"]),
                         ("EURUSD", 1000.0, leverage, 1.13146, 1.14284))
        polls = _polls(fake)
        self.assertEqual(polls[0][2]["params"],
                         {"orderId": str(accepted["orderId"])})
        self.assertEqual((r["orderId"], r["status"], r["executedQty"],
                          r["avgPrice"], r["positionId"]),
                         (str(accepted["orderId"]), "FILLED", "1000.0",
                          "1.13716", position))
        lk = r["raw"]["lookup"]
        self.assertEqual((lk["asset"]["settlementType"],
                          lk["asset"]["leverage"], lk["asset"]["symbol"],
                          lk["asset"]["instrumentId"]),
                         ("CFD", leverage, "EURUSD", 1))
        self.assertEqual(lk["openStopLossRate"], 1.13146,
                         "the top level keeps the SENT stop")
        first = lk["positionExecutions"][0]
        self.assertEqual((first["openingData"]["fees"],
                          first["openingData"]["marketSpread"],
                          first["initialExposureAccountCurrency"]),
                         (0.0, 0.01, 1137.16))
        with mock.patch("time.sleep"):
            c = t.close_position(position, "EURUSD",
                                 open_order_id=str(accepted["orderId"]))
        close_post = [x for x in fake.calls if x[0] == "POST"][1]
        self.assertTrue(close_post[1].endswith(
            f"/market-close-orders/positions/{position}"), close_post[1])
        self.assertEqual(close_post[2]["json"], {"InstrumentID": 1})
        self.assertEqual((c["status"], c["positionState"], c["orderId"],
                          c["openOrderId"]),
                         ("FILLED", "closed",
                          str(close["orderForClose"]["orderID"]),
                          str(accepted["orderId"])))
        self.assertNotIn("executedQty", c, "no units asked, none claimed")
        self.assertNotIn("avgPrice", c, "a close carries no price")
        self.assertEqual(t.margin_cells()["used_margin"], 0.0)
        for m, url, _k in fake.calls:
            if m == "POST":
                self.assertIn("/demo/", url, url)
                self.assertNotIn("/real/", url, url)
        return r, lk

    def test_proof_forex(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-28 22:42:46 UTC, by the
        operator the night before leaving: EURUSD 1000 units BUY at 1x,
        stop 1.13146 / target 1.14284 sent (the last 1.13715 x 0.995 /
        x 1.005). FILLED in 100 ms (requestTime .363Z -> executionTime
        .467Z) — order 384690781, position 3605812674, avgPrice 1.13716,
        settlementType CFD, requestedAmount 1137.16 = the whole notional,
        all of it locked (used margin 0.0 -> 1137.16), fees 0.0, markup
        0.03. eToro REWROTE the stop: sent 1.13146, held 1.12579 (1% under
        the fill) on positionExecutions[0]; the target held as sent.
        CLOSED by the market-close POST on the position id (orderForClose
        {orderID 384732103, orderType 19, statusID 1}), proven by the open
        order's execution state "closed" through one 500 on the way; used
        margin back to 0.0, available 332440.15 (the round trip cost
        0.01). "forex" joins ETORO_PROVEN in the commit that pins this.
        The eligibility row read the same minute: units fractional, floor
        1000 USD, LIVE leverages [1, 2, 5, 10, 20, 30]."""
        r, lk = self._fx_round_trip(1, FX_ACCEPTED_1X, FX_CLOSE_1X,
                                    FX_CELLS_AFTER_CLOSE_1X)
        self.assertEqual((r["venueStopLoss"], r["venueTakeProfit"]),
                         (1.12579, 1.14284), "the HELD stop, not the sent")
        first = lk["positionExecutions"][0]
        self.assertEqual((lk["requestedAmount"], lk["frozenAmount"],
                          first["marginAccountCurrency"],
                          first["openingData"]["markup"]),
                         (1137.16, 1137.16, 1137.16, 0.03))

    def test_proof_forex_at_5x(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-28 22:42:55 UTC, nine
        seconds after the 1x round trip closed: the same EURUSD 1000 units
        BUY at leverage 5, the same legs. FILLED in 123 ms — order
        384647176, position 3605812677, avgPrice 1.13716, asset.leverage 5,
        settlementType CFD; requestedAmount 227.43 = notional / 5, margin
        227.42 (used margin 0.0 -> 227.42), exposure 1137.16 unchanged:
        leverage changes the cash locked, never the units. The stop was
        HELD AS SENT (1.13146) this time. CLOSED by position id
        (orderForClose {orderID 384726349, orderType 19, statusID 1}),
        proven "closed" through one 500; used margin 0.0, available
        332440.14. forex enters ETORO_PROVEN_LEVERAGE at 5 in the commit
        that pins this: the attack mode's chooser may pick up to 5x on
        forex, and a typed multiplier is judged as before."""
        r, lk = self._fx_round_trip(5, FX_ACCEPTED_5X, FX_CLOSE_5X,
                                    FX_CELLS_AFTER_CLOSE_5X)
        self.assertEqual((r["venueStopLoss"], r["venueTakeProfit"]),
                         (1.13146, 1.14284), "held as sent at 5x")
        first = lk["positionExecutions"][0]
        self.assertEqual((lk["requestedAmount"], lk["frozenAmount"],
                          first["marginAccountCurrency"],
                          first["openingData"]["markup"]),
                         (227.43, 227.43, 227.42, 0.04))
        self.assertAlmostEqual(lk["requestedAmount"] * 5,
                               first["initialExposureAccountCurrency"],
                               places=1)

    def _class_round_trip(self, token, proofs=None):
        """One 2026-09-29 class proof through the real adapter over the fake
        wire: the order on the demo segment, the fill read by orderId
        through the 404s it met first, the close by position id proven by
        the OPEN order through the 500s that close met, the cells after."""
        p = (proofs or CLASS_PROOFS)[token]
        order_id, position = str(p["order"]), str(p["position"])
        fill_404s = p.get("fill_404s", 0)
        t, fake = self._t(
            [(404, {})] * fill_404s
            + [(200, _class_lookup(p, "open"))]
            + [(500, {})] * p["close_500s"]
            + [(200, _class_lookup(p, "closed"))],
            routes=[
                ("GET", "/market-data/search", 200,
                 [{"instrumentId": p["iid"],
                   "internalSymbolFull": p["venue"]}]),
                ("POST", "/execution/demo/orders", 200,
                 {"token": "<not captured>", "orderId": p["order"],
                  "referenceId": "<not captured>"}),
                ("POST", f"/market-close-orders/positions/{position}", 200,
                 _class_close(p)),
                ("GET", "/aggregate-portfolio", 200,
                 {"accountCurrency": "USD",
                  "accountTotals": {
                      "accountAvailableCash": p["cash_after_close"],
                      "accountTotalUsedMargin": 0.0}})])
        with mock.patch("time.sleep"):
            r = t.market_order(p["symbol"], p.get("order_side", "BUY"),
                               p["units"], stop_loss=p["sent"][0],
                               take_profit=p["sent"][1])
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(post[1],
                         f"{BASE}/api/v2/trading/execution/demo/orders")
        body = post[2]["json"]
        self.assertEqual(body["transaction"],
                         "sellShort" if p.get("order_side") == "SELL"
                         else "buy")
        self.assertEqual((body["symbol"], float(body["units"]),
                          body["leverage"], body["stopLossRate"],
                          body["takeProfitRate"]),
                         (p["venue"], p["units"], 1) + p["sent"])
        self.assertEqual(_polls(fake)[0][2]["params"], {"orderId": order_id})
        self.assertEqual((r["orderId"], r["status"], r["executedQty"],
                          r["avgPrice"], r["positionId"]),
                         (order_id, "FILLED", str(p["units"]),
                          str(p["avg"]), position))
        self.assertEqual((r["venueStopLoss"], r["venueTakeProfit"]),
                         p["held"], "the HELD legs, rounded by eToro")
        lk = r["raw"]["lookup"]
        self.assertEqual((lk["asset"]["settlementType"],
                          lk["asset"]["leverage"], lk["asset"]["symbol"],
                          lk["asset"]["instrumentId"]),
                         (p["settlement"], 1, p["venue"], p["iid"]))
        self.assertEqual((lk["openStopLossRate"], lk["openTakeProfitRate"]),
                         p["sent"], "the top level keeps the SENT legs")
        first = lk["positionExecutions"][0]
        self.assertEqual((lk["requestedAmount"], lk["frozenAmount"],
                          first["marginAccountCurrency"],
                          first["openingData"]["fees"],
                          first["openingData"]["markup"]),
                         (p["requested"], p["frozen"], p["margin"],
                          p["fees"], p["markup"]))
        with mock.patch("time.sleep"):
            c = t.close_position(position, p["symbol"], open_order_id=order_id)
        close_post = [x for x in fake.calls if x[0] == "POST"][1]
        self.assertTrue(close_post[1].endswith(
            f"/market-close-orders/positions/{position}"), close_post[1])
        self.assertEqual(close_post[2]["json"], {"InstrumentID": p["iid"]})
        self.assertEqual((c["status"], c["positionState"], c["orderId"],
                          c["openOrderId"]),
                         ("FILLED", "closed", str(p["close_order"]), order_id))
        self.assertNotIn("executedQty", c, "no units asked, none claimed")
        self.assertNotIn("avgPrice", c, "a close carries no price")
        self.assertEqual(len(_polls(fake)),
                         fill_404s + 1 + p["close_500s"] + 1,
                         "the fill read through its 404s, the close proven "
                         "through its 500s")
        self.assertEqual(t.margin_cells()["used_margin"], 0.0)
        for m, url, _k in fake.calls:
            if m == "POST":
                self.assertIn("/demo/", url, url)
                self.assertNotIn("/real/", url, url)
        return r, lk

    def test_proof_stock(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-29 10:57:01 UTC, by the
        operator the day of leaving: AAPL 4 units BUY at 1x, stop 326.6184 /
        target 346.8216 sent (the last 336.72 x 0.97 / x 1.03). FILLED in
        ~150 ms — order 384798829, position 3605938942, avgPrice 336.87,
        settlementType REAL (a stock at 1x is the share itself, as BTC was
        on the real account), requestedAmount 1347.52, frozenAmount 1348.52
        (the notional and the 1.00 fee: totalCosts 1.0, fees 1.0, markup
        0.0, marketSpread 0.64), used margin 0.0 -> 1347.48. The legs HELD
        as 326.62 / 346.82. CLOSED by position id (orderForClose {orderID
        384822839, orderType 19, statusID 1}), proven "closed" through two
        500s; used margin 0.0, available 332437.62 (the round trip cost
        2.52 of 332440.14). The eligibility row the same minute: units
        fractional, floor 10 USD, open True. "stock" joins ETORO_PROVEN in
        the commit that pins this, at 1x, BUY only ("short" stays out)."""
        r, lk = self._class_round_trip("stock")
        self.assertEqual(lk["totalCosts"], 1.0, "a stock pays a fee to open")

    def test_proof_index(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-29 10:57:15 UTC, fourteen
        seconds after the AAPL close: SPX500 1 unit BUY at 1x, stop
        7458.5531 / target 7919.9069 sent (the last 7689.23 x 0.97 /
        x 1.03). FILLED in ~110 ms — order 384769149, position 3605939058,
        avgPrice 7689.63, settlementType CFD, requestedAmount 7689.63 = the
        whole notional, all of it locked (used margin 0.0 -> 7689.63),
        fees 0.0, markup 0.04, marketSpread 0.4. The legs HELD as 7458.56 /
        7919.9. CLOSED by position id (orderForClose {orderID 384793580,
        orderType 19, statusID 1}), proven "closed" through one 500; used
        margin 0.0, available 332437.22. Eligibility: units fractional,
        floor 1000 USD, open True. "index" joins ETORO_PROVEN in the commit
        that pins this, at 1x: it lifts SPX500, NSDQ100 and DJ30 (USD
        quoted); the indices in VENUE_QUOTE_UNMEASURED stay refused
        whatever this set holds, because the engine sizes a point of their
        price as one USD."""
        r, lk = self._class_round_trip("index")
        self.assertEqual(lk["requestedAmount"],
                         lk["positionExecutions"][0]["initialExposureAccountCurrency"],
                         "at 1x the whole notional is locked")

    def test_proof_commodity(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-29 10:57:25 UTC: the
        platform's WHEATUSD, sent to eToro as WHEAT.FUT (id 97, through
        VENUE_SPELLING — the order body carries eToro's spelling), 2 units
        BUY at 1x, stop 662.995 / target 704.005 sent (the last 683.5 x
        0.97 / x 1.03). FILLED in ~130 ms — order 384769151, position
        3605939068, avgPrice 683.75, settlementType CFD, requestedAmount
        1367.5 = the notional (one unit is priced as 683.5 USD: the quote
        in cents a bushel reads as dollars a unit), fees 0.0, markup 0.06,
        marketSpread 0.5, used margin 0.0 -> 1367.5. The legs HELD as
        663.0 / 704.0. CLOSED by position id (orderForClose {orderID
        384813052, orderType 19, statusID 1}), proven "closed" through one
        500; used margin 0.0, available 332436.72; /portfolio [] 60 s
        later. Eligibility: units fractional, floor 1000 USD, open True.
        "commodity" joins ETORO_PROVEN in the commit that pins this, at
        1x: it lifts the gate only; the router sends a commodity to eToro
        only with eToro's commodities box ticked, and gold, silver and oil
        still have no measured eToro spelling."""
        r, lk = self._class_round_trip("commodity")
        self.assertEqual(lk["asset"]["symbol"], "WHEAT.FUT")

    def test_proof_short_stock(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-10-01 21:02:19 UTC, the first
        eToro SELL that ever filled: AAPL 4 units SELL at 1x ("sellShort"),
        stop 339.91 ABOVE / target 320.11 BELOW sent (the last 330.01 x
        1.03 / x 0.97). FILLED in ~130 ms after one 404 on the fill poll —
        order 385673365, position 3608630747, avgPrice 330.01,
        settlementType CFD (a short is never the share), side "short",
        requestedAmount 1320.04, frozenAmount 1322.02 (the notional and the
        1.98 fee: totalCosts 1.98, markup 0.08, marketSpread 1.24), used
        margin 0.0 -> 1320.04. The legs HELD as sent. CLOSED by position id
        (orderForClose {orderID 385717837, orderType 19, statusID 1}),
        proven "closed" through three 500s; used margin 0.0, available
        332429.12; /portfolio [] 60 s later. The eligibility row the same
        minute: LIVE short CFD leverage [1, 2, 5], floor 10 USD, open True.
        "stock" joins ETORO_SHORT_PROVEN in the commit that pins this."""
        r, lk = self._class_round_trip("stock", CLASS_SHORT_PROOFS)
        self.assertEqual((lk["transaction"], lk["asset"]["side"]),
                         ("sell", "short"))
        stop, target = CLASS_SHORT_PROOFS["stock"]["held"]
        self.assertGreater(stop, float(r["avgPrice"]),
                           "a short's stop rests ABOVE the fill")
        self.assertLess(target, float(r["avgPrice"]))
        self.assertEqual(lk["totalCosts"], 1.98, "the short paid its fee")

    def test_proof_short_forex(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-10-01 21:17:11 UTC: EURUSD 1000
        units SELL at 1x, stop 1.1573 ABOVE / target 1.08988 BELOW sent (the
        last 1.12359 x 1.03 / x 0.97, five decimals). FILLED in ~80 ms —
        order 385673393, position 3608631633, avgPrice 1.12453,
        settlementType CFD, side "short", requestedAmount 1124.53 = the
        whole notional at 1x, no fee (totalCosts 0.0, markup 0.03,
        marketSpread 0.22), used margin 0.0 -> 1124.53. The legs HELD as
        sent. CLOSED by position id (orderForClose {orderID 385717862,
        orderType 19, statusID 1}), proven "closed" through three 500s;
        used margin 0.0, available 332428.9. The eligibility row: LIVE short
        CFD leverage [1, 2, 5, 10, 20, 30], floor 1000 USD, open True.
        "forex" joins ETORO_SHORT_PROVEN in the commit that pins this."""
        r, lk = self._class_round_trip("forex", CLASS_SHORT_PROOFS)
        self.assertEqual((lk["transaction"], lk["asset"]["side"]),
                         ("sell", "short"))
        self.assertGreater(CLASS_SHORT_PROOFS["forex"]["held"][0],
                           float(r["avgPrice"]))
        self.assertEqual(lk["requestedAmount"],
                         lk["positionExecutions"][0]["marginAccountCurrency"],
                         "at 1x the whole notional is locked")

    def test_a_short_rejected_with_749_is_read_as_rejected_with_its_words(self):
        """MEASURED 2026-10-01 21:01:38 UTC, demo: SPX500 1 unit SELL at 1x,
        stop 7902.74 / target 7442.38 sent. The order POST was accepted
        (orderId 385673361) and the lookup answered status {id 4,
        "Rejected", errorCode 749, "Error creating entry order - disallowed
        for instrument(27)"}, no positionExecutions, nothing locked. The
        adapter reads it REJECTED with eToro's words and no position — the
        engine books nothing. EURUSD's SELL 21 s later read the same with
        instrument(1) inside New York's 17:00 rollover — and filled at
        21:17 (test_proof_short_forex). SPX500 and NSDQ100 were rejected
        749 again at 1x and 2x at 21:17: "index" stays out of
        ETORO_SHORT_PROVEN."""
        rejected = {
            "accountId": 15153738, "gcid": 13883661, "portfolioId": 0,
            "orderId": 385673361, "action": "open", "transaction": "sell",
            "type": "mkt", "etoroOrderTypeId": 18,
            "status": {"id": 4, "name": "Rejected", "errorCode": 749,
                       "errorMessage": "Error creating entry order - "
                                       "disallowed for instrument(27)"},
            "asset": {"symbol": "SPX500", "instrumentId": 27,
                      "currency": "USD", "settlementType": "CFD",
                      "leverage": 1, "side": "short"},
            "orderCurrency": "usd", "requestedAmount": 0.0,
            "requestedUnits": 1.0, "requestedContracts": 0.0,
            "openStopLossRate": 7902.74, "openTakeProfitRate": 7442.38,
            "stopLossType": "fixed", "totalCosts": 0.0,
            "positionsToClose": [], "positionExecutions": [],
            "requestTime": "2026-10-01T21:01:38.603Z",
            "lastUpdate": "2026-10-01T21:01:38.603Z",
            "openActionType": "customer", "requestType": "byUnits"}
        t, fake = self._t(
            [(200, rejected)],
            routes=[("GET", "/market-data/search", 200,
                     [{"instrumentId": 27, "internalSymbolFull": "SPX500"}]),
                    ("POST", "/execution/demo/orders", 200,
                     {"token": "<not captured>", "orderId": 385673361,
                      "referenceId": "<not captured>"})])
        with mock.patch("time.sleep"):
            r = t.market_order("SPX500", "SELL", 1.0, stop_loss=7902.74,
                               take_profit=7442.38)
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(r["executedQty"], "0.0")
        self.assertFalse(r.get("positionId"))
        self.assertIn("749", r["refusal"])
        self.assertIn("disallowed for instrument(27)", r["refusal"])

    def test_proof_stock_fraction(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-29 12:02:23 UTC (§4 D2c-1
        for a stock): AAPL 0.05 BUY at 1x FILLED as 0.05 exactly
        (requestedUnits = openingData.units = remainingUnits 0.05), order
        384799082, avgPrice 337.21, settlementType REAL, requestedAmount
        16.86, frozenAmount 17.86: the 1.00 fee is FLAT, the same 1.00 as
        on 4 units (test_proof_stock). Closed by id through one 500; the
        round trip cost 1.98 of 16.86 — 11.7% of the position, the fee
        twice. risk_levels.ETORO_STOCK_FEE_USD_PER_SIDE is this number."""
        r, lk = self._class_round_trip("stock", CLASS_FRACTION_PROOFS)
        first = lk["positionExecutions"][0]
        self.assertEqual((lk["requestedUnits"], first["openingData"]["units"],
                          first["remainingUnits"]), (0.05, 0.05, 0.05))
        self.assertEqual((first["openingData"]["fees"], lk["totalCosts"]),
                         (1.0, 1.0), "the same flat 1.00 as on 4 units")
        from bot_program.asset_engine.risk_levels import (
            ETORO_STOCK_FEE_USD_PER_SIDE)
        self.assertEqual(ETORO_STOCK_FEE_USD_PER_SIDE,
                         first["openingData"]["fees"])

    def test_proof_index_fraction(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-29 12:02:35 UTC: SPX500
        0.14 BUY at 1x (1078.63 of notional, above the 1000 USD floor)
        FILLED as 0.14 exactly, order 384769398, avgPrice 7704.5, CFD, the
        whole notional locked, fees 0.0. Closed by id through one 500; the
        round trip cost 0.04."""
        r, lk = self._class_round_trip("index", CLASS_FRACTION_PROOFS)
        first = lk["positionExecutions"][0]
        self.assertEqual((lk["requestedUnits"], first["openingData"]["units"],
                          first["remainingUnits"]), (0.14, 0.14, 0.14))
        self.assertGreaterEqual(lk["requestedAmount"], 1000.0,
                                "above eToro's 1000 USD index floor")

    def test_proof_commodity_fraction(self):
        """MEASURED ON THE DEMO SEGMENT, 2026-09-29 12:02:45 UTC: WHEATUSD
        as WHEAT.FUT 1.5 BUY at 1x (1033.5 of notional) FILLED as 1.5
        exactly, order 384799086, avgPrice 689.0, CFD, fees 0.0, markup
        3.0. Its first fill poll answered 404, its close proof met three
        500s before "closed"; the round trip cost 0.38."""
        r, lk = self._class_round_trip("commodity", CLASS_FRACTION_PROOFS)
        first = lk["positionExecutions"][0]
        self.assertEqual((lk["requestedUnits"], first["openingData"]["units"],
                          first["remainingUnits"]), (1.5, 1.5, 1.5))

    def test_the_accepted_payload_is_token_int_orderid_and_the_echoed_reference(self):
        t, fake = self._t((200, _measured_lookup()))
        out = self._order(t)
        self.assertEqual(out["orderId"], "383454450")
        acc = out["raw"]["accepted"]
        self.assertIs(type(acc["orderId"]), int)
        self.assertEqual(acc["referenceId"],
                         "c03112d0-7e9c-4186-abb9-39027a79aa91")
        self.assertIn("token", acc)
        polls = _polls(fake)
        self.assertEqual(len(polls), 1, "a 200 ms fill is read on the first poll")
        self.assertEqual(polls[0][2]["params"], {"orderId": "383454450"})

    def test_the_fill_is_looked_up_by_orderid_never_by_the_reference_etoro_forgets(self):
        """Under aa5cfb2 this exact wire read PENDING/working/pollFailed for a
        filled order: the poll went by referenceId and eToro answered 404."""
        t, fake = self._t((200, _measured_lookup()))
        out = self._order(t)
        self.assertEqual(out["status"], "FILLED")
        self.assertNotIn("working", out)
        self.assertNotIn("pollFailed", out)
        for _m, _u, k in _polls(fake):
            self.assertNotIn("referenceId", k.get("params") or {})

    def test_reference_id_is_only_a_fallback_when_the_acceptance_names_no_orderid(self):
        """An acceptance with no orderId is a shape nobody has seen; the
        documented fallback then means 404 -> pollFailed, never a fill."""
        from bot_program.engine.etoro_client import FILL_ATTEMPTS
        t, fake = self._t((200, _measured_lookup()), routes=[
            SEARCH_GLDM, ("POST", "/execution/demo/orders", 200,
                          {"token": "t", "referenceId": "ref-x"})])
        out = self._order(t)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out.get("working"))
        self.assertTrue(out.get("pollFailed"))
        polls = _polls(fake)
        self.assertEqual(len(polls), FILL_ATTEMPTS)
        for _m, _u, k in polls:
            self.assertEqual(k["params"], {"referenceId": "ref-x"})

    def test_the_token_is_never_used_as_a_lookup_key(self):
        t, fake = self._t((200, _measured_lookup()))
        self._order(t)
        for _m, _u, k in _polls(fake):
            self.assertNotIn("token", k.get("params") or {})

    def test_a_measured_fill_is_read_off_position_executions(self):
        body = _measured_lookup()
        t, _ = self._t((200, body))
        out = self._order(t)
        self.assertEqual(out["executedQty"], "1.0")
        self.assertEqual(out["avgPrice"], "84.8")
        self.assertEqual(out["positionId"], "3603281458")
        self.assertEqual(out["venueStopLoss"], 82.22)
        self.assertEqual(out["venueTakeProfit"], 87.3)
        self.assertTrue(out.get("protectedOnFill"))
        self.assertEqual(out.get("protectiveTradeId"), "3603281458")
        self.assertIs(out["raw"]["lookup"], body)
        first = out["raw"]["lookup"]["positionExecutions"][0]
        self.assertEqual(first["openingData"]["fees"], 0.13)
        self.assertEqual(first["marginAccountCurrency"], 84.8)
        self.assertEqual(out["raw"]["lookup"]["asset"]["settlementType"], "CFD")

    def test_the_status_object_id_three_is_filled_with_no_words(self):
        """The wire's `name` is not promoted over STATUS_NAMES: the one name
        measured agrees with the table."""
        from bot_program.engine.etoro_client import _status_of
        self.assertEqual(_status_of(_measured_lookup()), (3, ""))
        self.assertEqual(_status_of(_measured_lookup("closed")), (3, ""),
                         "status is NOT the close proof")
        t, _ = self._t((200, _measured_lookup()))
        self.assertEqual(self._order(t)["raw"]["statusName"], "Filled")

    def test_a_levered_fill_keeps_its_units_and_halves_the_margin(self):
        body = _measured_lookup(order_id=383458277, leverage=2, avg=84.79,
                                margin=42.39, exposure=84.79, requested=42.4,
                                frozen=42.53, markup=0.01,
                                position_id=3603285267)
        t, fake = self._t((200, body), routes=[
            SEARCH_GLDM, ("POST", "/execution/demo/orders", 200,
                          {"token": "t", "orderId": 383458277,
                           "referenceId": "r"})])
        out = self._order(t, leverage=2)
        posted = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(posted["leverage"], 2)
        self.assertEqual(posted["units"], 1.0)
        self.assertEqual(out["executedQty"], "1.0")
        self.assertEqual(out["avgPrice"], "84.79")
        self.assertEqual(out["venueStopLoss"], 82.22)
        ex = body["positionExecutions"][0]
        self.assertAlmostEqual(body["requestedAmount"],
                               ex["initialExposureAccountCurrency"] / 2,
                               places=1)
        self.assertAlmostEqual(body["frozenAmount"],
                               body["requestedAmount"] + ex["openingData"]["fees"],
                               places=2)

    def test_one_failed_poll_before_a_fill_is_not_pollfailed(self):
        t, fake = self._t([(500, {}), (200, _measured_lookup())])
        out = self._order(t)
        self.assertEqual(out["status"], "FILLED")
        self.assertNotIn("pollFailed", out)
        self.assertEqual(len(_polls(fake)), 2)

    def test_pollfailed_only_when_every_lookup_failed(self):
        from bot_program.engine.etoro_client import FILL_ATTEMPTS
        t, fake = self._t((500, {}))
        out = self._order(t)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out.get("working"))
        self.assertTrue(out.get("pollFailed"))
        self.assertEqual(out["executedQty"], "0.0")
        self.assertEqual(len(_polls(fake)), FILL_ATTEMPTS)
        t, fake = self._t([(500, {}), (503, {}), (200, {"status": 1})])
        out = self._order(t)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out.get("working"))
        self.assertNotIn("pollFailed", out)

    def test_pending_only_on_a_real_non_filled_status(self):
        """The INT form of status 1 is the older fixture; id 1's object
        spelling is UNMEASURED."""
        t, _ = self._t((200, {"status": 1}))
        out = self._order(t)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out.get("working"))
        self.assertNotIn("pollFailed", out)

    def test_every_lookup_refused_by_quota_is_pollfailed_never_a_fill(self):
        from bot_program.engine.etoro_client import (CLOSE_PROOF_ATTEMPTS,
                                                     FILL_ATTEMPTS)
        t, fake = self._t((429, {}))
        out = self._order(t)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out.get("pollFailed"))
        self.assertLessEqual(len(_polls(fake)), FILL_ATTEMPTS)
        self.assertLessEqual(FILL_ATTEMPTS + CLOSE_PROOF_ATTEMPTS, 20)

    def test_the_close_proof_is_the_open_orders_execution_state_turning_closed(self):
        t, fake = self._t((200, _measured_lookup("closed")))
        with mock.patch("time.sleep"):
            self.assertEqual(t.position_state("383454450", until="closed"),
                             "closed")
        polls = _polls(fake)
        self.assertEqual(len(polls), 1)
        self.assertEqual(polls[0][2]["params"], {"orderId": "383454450"})

    def test_a_500_during_the_close_is_transient_and_the_proof_still_arrives(self):
        """The 500 x3 then 200 sequence and the ~8 s were measured on the 2x
        close (order 383458277)."""
        from bot_program.engine.etoro_client import (CLOSE_PROOF_ATTEMPTS,
                                                     CLOSE_PROOF_DELAY_S)
        t, fake = self._t([(500, {}), (500, {}), (500, {}),
                           (200, _measured_lookup("closed"))])
        with mock.patch("time.sleep") as sleep:
            self.assertEqual(t.position_state("383454450", until="closed"),
                             "closed")
        self.assertEqual(len(_polls(fake)), 4)
        self.assertEqual(sleep.call_count, 4)
        self.assertGreaterEqual(CLOSE_PROOF_ATTEMPTS * CLOSE_PROOF_DELAY_S, 8)

    def test_an_all_500_proof_is_none_never_closed(self):
        from bot_program.engine.etoro_client import CLOSE_PROOF_ATTEMPTS
        t, fake = self._t((500, {}))
        with mock.patch("time.sleep"):
            self.assertIsNone(t.position_state("383454450", until="closed"))
        self.assertEqual(len(_polls(fake)), CLOSE_PROOF_ATTEMPTS)
        t, _ = self._t((404, {"message": "Order category for 383454450 not found"}))
        with mock.patch("time.sleep"):
            self.assertIsNone(t.position_state("383454450", until="closed"))
        t, _ = self._t((200, {"status": {"id": 3}, "positionExecutions": []}))
        with mock.patch("time.sleep"):
            self.assertIsNone(t.position_state("383454450", until="closed"))
        self.assertIsNone(t.position_state(""))

    def test_a_proof_that_reads_open_keeps_polling_then_answers_open(self):
        from bot_program.engine.etoro_client import CLOSE_PROOF_ATTEMPTS
        t, fake = self._t((200, _measured_lookup("open")))
        with mock.patch("time.sleep"):
            self.assertEqual(t.position_state("383454450", until="closed"),
                             "open")
        self.assertEqual(len(_polls(fake)), CLOSE_PROOF_ATTEMPTS)
        t, fake = self._t((200, _measured_lookup("open")))
        with mock.patch("time.sleep"):
            self.assertEqual(t.position_state("383454450"), "open")
        self.assertEqual(len(_polls(fake)), 1)
        t, fake = self._t((200, _measured_lookup("open")))
        with mock.patch("time.sleep") as sleep:
            self.assertEqual(t.position_state("383454450", attempts=1,
                                              delay=0.0), "open")
        self.assertEqual(len(_polls(fake)), 1)
        sleep.assert_not_called()

    def test_a_proven_close_reports_the_units_and_no_price(self):
        """`UnitsToDeduct` is NEVER sent (measured 2026-09-23 17:43-17:58
        UTC: two closes carrying it were accepted and never executed; the
        same close with InstrumentID alone executed in ~6 s). The 500 x3
        sequence was measured on the 2x close and is played against the 1x
        close response here: the proof reader is one code."""
        t, fake = self._closer([(500, {}), (500, {}), (500, {}),
                                (200, _measured_lookup("closed"))])
        with mock.patch("time.sleep"):
            out = t.close_position("3603281458", "GLDM", 1.0,
                                   open_order_id="383454450")
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["executedQty"], "1.0")
        self.assertNotIn("avgPrice", out)
        self.assertEqual(out["orderId"], "383413813")
        self.assertEqual(out["positionId"], "3603281458")
        self.assertEqual(out["openOrderId"], "383454450")
        self.assertEqual(out["positionState"], "closed")
        self.assertIs(out["raw"], CLOSE_RESPONSE)
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertIn("/api/v1/trading/execution/demo/market-close-orders/"
                      "positions/3603281458", post[1])
        self.assertEqual(post[2]["json"], {"InstrumentID": 3190},
                         "UnitsToDeduct makes eToro accept a close it never "
                         "executes (measured 2026-09-23)")

    def test_a_close_the_venue_has_not_proven_is_pending_with_nothing_filled(self):
        t, _ = self._closer((500, {}))
        with mock.patch("time.sleep"):
            out = t.close_position("3603281458", "GLDM", 1.0,
                                   open_order_id="383454450")
        self.assertEqual(out["status"], "PENDING")
        self.assertEqual(out["executedQty"], "0.0")
        self.assertIsNone(out["positionState"])
        self.assertNotIn("avgPrice", out)
        t, _ = self._closer((200, _measured_lookup("open")))
        with mock.patch("time.sleep"):
            out = t.close_position("3603281458", "GLDM", 1.0,
                                   open_order_id="383454450")
        self.assertEqual(out["status"], "PENDING")
        self.assertEqual(out["executedQty"], "0.0")
        self.assertEqual(out["positionState"], "open")

    def test_a_close_without_the_open_order_id_is_pending_and_asks_nothing(self):
        t, fake = self._closer((200, _measured_lookup("closed")))
        out = t.close_position("3603281458", "GLDM")
        self.assertEqual(out["status"], "PENDING")
        self.assertEqual(out["executedQty"], "0.0")
        self.assertNotIn("positionState", out)
        self.assertEqual(_polls(fake), [])
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(post[2]["json"], {"InstrumentID": 3190})

    def test_the_close_order_id_is_never_used_as_a_handle(self):
        import inspect
        from bot_program import pending_closes
        t, fake = self._closer((200, _measured_lookup("closed")))
        with mock.patch("time.sleep"):
            t.close_position("3603281458", "GLDM", 1.0,
                             open_order_id="383454450")
        for _m, _u, k in _polls(fake):
            self.assertEqual(k["params"], {"orderId": "383454450"})
        src = inspect.getsource(pending_closes.venue_position_state)
        self.assertIn("broker_order_id", src)
        self.assertNotIn("CLOSE_WORKING_ORDER_ID_KEY", src)

    def test_the_portfolio_row_is_nested_and_spelt_with_capital_id(self):
        t, _ = _client([SEARCH_GLDM,
                        ("GET", "/info/demo/portfolio", 200,
                         {"clientPortfolio": {"positions": [PORTFOLIO_ROW]}})])
        t.instrument_id("GLDM")
        self.assertEqual(t.get_positions(),
                         [{"symbol": "GLDM", "qty": 1.0, "side": "BUY",
                           "position_id": "3603281458"}])
        rows = t.broker_portfolio()
        self.assertEqual(rows[0]["leverage"], 1)
        self.assertEqual(rows[0]["symbol"], "GLDM")
        self.assertNotIn("positionId", PORTFOLIO_ROW)

    def test_the_portfolio_lag_is_a_named_constant_the_readers_read(self):
        from pathlib import Path
        from django.conf import settings
        from bot_program.engine.etoro_client import PORTFOLIO_LAG_S
        self.assertEqual(PORTFOLIO_LAG_S, 60)
        self.assertEqual(EtoroTrader.PORTFOLIO_LAG_S, 60)
        t, _ = _client([])
        self.assertEqual(t.PORTFOLIO_LAG_S, 60)
        base = Path(settings.BASE_DIR) / "bot_program"
        ra = (base / "reconcile_asset.py").read_text(encoding="utf-8")
        self.assertIn('getattr(client, "PORTFOLIO_LAG_S", 0)', ra)
        self.assertIn("isinstance(lag, (int, float))", ra)
        pc = (base / "pending_closes.py").read_text(encoding="utf-8")
        self.assertIn("venue_lag_window(trade, client)", pc)

    def test_the_margin_cells_move_with_the_fill_and_the_close_in_the_same_second(self):
        def cells(moment):
            v, c, u = MOMENTS[moment]
            t, _ = _client([("GET", "/aggregate-portfolio", 200,
                             _totals(v, c, u))])
            return t.margin_cells(), t.net_liquidation()
        m, nl = cells("after D2 fill (1x)")
        self.assertEqual(m, {"available_cash": 332364.17, "used_margin": 84.8,
                             "currency": "USD"})
        self.assertEqual(nl, (332448.94, "USD"))
        self.assertEqual(cells("after D2 close")[0]["used_margin"], 0.0)
        self.assertEqual(cells("after D2b-ii fill (2x)")[0]["used_margin"],
                         42.39)
        self.assertEqual(cells("after D2 fill (1x)")[0]["used_margin"],
                         _measured_lookup()["positionExecutions"][0]
                         ["marginAccountCurrency"])
        cash = {k: v[1] for k, v in MOMENTS.items()}
        self.assertAlmostEqual(cash["before D2"] - cash["after D2 fill (1x)"],
                               84.8 + 0.13, places=2)
        self.assertAlmostEqual(cash["after D2 close"]
                               - cash["after D2b-ii fill (2x)"],
                               42.39 + 0.13, places=2)

    def test_a_tighter_stop_patch_echoes_in_the_open_orders_lookup(self):
        t, fake = _client([SEARCH_GLDM,
                           ("PATCH", "/positions/3603285267", 200, {})])
        self.assertEqual(t.modify_protective("3603285267", 83.06),
                         {"ok": True, "reason": "", "price": 83.06})
        patched = [c for c in fake.calls if c[0] == "PATCH"][0]
        self.assertIn("/api/v2/trading/demo/positions/3603285267", patched[1])
        self.assertEqual(patched[2]["json"], {"stopLossRate": 83.06})
        _lookup_router(fake, by_order=(200, _measured_lookup(
            order_id=383458277, stop=83.06, position_id=3603285267)))
        body, code = t._lookup_once({"orderId": "383458277"})
        self.assertEqual(code, 200)
        self.assertEqual(body["positionExecutions"][0]["stopLossRate"], 83.06)
        self.assertEqual(body["positionExecutions"][0]["takeProfitRate"], 87.3)




# ── the held order, its poll and its withdrawal (D3b) ──────────────────────

class TheHeldOrderTests(SimpleTestCase):
    """D2b-i measured 2026-09-23 20:29 UTC on the demo segment, byte for byte,
    with the real EtoroTrader over a patched session: status 11 while held,
    the pre-index 404, DELETE v3 -> 202 -> lookup 7, the margin pledged by a
    held order; and the floor refusal (status 4 / 720) on the poll path."""

    def _t(self, by_order, routes=None):
        t, fake = _client(list(routes if routes is not None
                               else [SEARCH_GLDM, POST_HELD]))
        _lookup_router(fake, by_order=by_order)
        return t, fake

    def _deletes(self, fake):
        return [c for c in fake.calls if c[0] == "DELETE"]

    def test_a_held_order_reads_404_then_waiting_for_market_and_books_working(self):
        """The 404 cost one attempt, the second read WaitingForMarket, the
        poll ran its whole budget and answered working: the ride-through pin
        is `pollFailed` absent, not a count of two."""
        from bot_program.engine.etoro_client import FILL_ATTEMPTS
        t, fake = self._t([LOOKUP_404_NOT_INDEXED, (200, _held_lookup())])
        with mock.patch("time.sleep"):
            out = t.market_order("GLDM", "BUY", 1, stop_loss=82.17,
                                 take_profit=87.25, leverage=2)
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out.get("working"))
        self.assertNotIn("pollFailed", out)
        self.assertEqual(out["raw"]["statusName"], "WaitingForMarket")
        self.assertEqual(out["executedQty"], "0.0")
        for absent in ("positionId", "venueStopLoss", "protectedOnFill"):
            self.assertNotIn(absent, out)
        self.assertEqual(len(_polls(fake)), FILL_ATTEMPTS)

    def test_order_status_maps_eleven_working_three_filled_seven_dead_four_dead(self):
        t, fake = self._t((200, _held_lookup()))
        st = t.order_status("383459788")
        self.assertEqual((st["state"], st["status"], st["statusId"],
                          st["filled"], st["avgPrice"]),
                         ("working", "WaitingForMarket", 11, 0.0, 0.0))
        self.assertNotIn("positionId", st)
        self.assertNotIn("refusal", st)
        self.assertEqual(len(_polls(fake)), 1)
        t, _ = self._t((200, _measured_lookup()))
        st = t.order_status("383454450")
        self.assertEqual((st["state"], st["filled"], st["avgPrice"],
                          st["positionId"], st["venueStopLoss"],
                          st["venueTakeProfit"]),
                         ("filled", 1.0, 84.8, "3603281458", 82.22, 87.3))
        t, _ = self._t((200, _rewritten_fill()))
        st = t.order_status("383459788")
        self.assertEqual(st["venueStopLoss"], 83.06,
                         "the HELD stop lives in positionExecutions[0], never "
                         "on the top-level openStopLossRate")
        t, _ = self._t((200, CANCELED_LOOKUP))
        st = t.order_status("383459788")
        self.assertEqual((st["state"], st["filled"]), ("dead", 0.0))
        self.assertNotIn("refusal", st)
        t, _ = self._t((200, REJECTED_720))
        st = t.order_status("383455967")
        self.assertEqual(st["state"], "dead")
        self.assertTrue(st["refusal"].startswith(
            "errorCode 720: Error opening position"))
        self.assertTrue(st["refusal"].endswith(
            "InitialPositionAmount: 8.44 MinimumPositionAmount: 10 (Dollars)"),
            "the WHOLE measured message rides refusal since 2026-09-24: "
            "the amount and the minimum are its last words")
        self.assertGreater(len(st["refusal"]), len("errorCode 720: ") + 120)

    def test_order_status_three_states(self):
        t, fake = self._t((404, {"message": "Order category for x not found"}))
        self.assertEqual(t.order_status("383413813")["state"], "unknown")
        t, _ = self._t((500, {}))
        self.assertIsNone(t.order_status("383459788"))
        t, _ = self._t((429, {}))
        self.assertIsNone(t.order_status("383459788"))
        t, _ = self._t((200, {"status": {"id": 3}, "positionExecutions": []}))
        st = t.order_status("383459788")
        self.assertEqual(st["state"], "unknown")
        self.assertIn("nobody has seen", st["reason"])
        t, fake = self._t((200, _held_lookup()))
        st = t.order_status("")
        self.assertEqual(st["state"], "unknown")
        self.assertEqual(_polls(fake), [])
        t, _ = self._t((200, _lookup(5, units=0.4)))
        st = t.order_status("1")
        self.assertEqual((st["state"], st["filled"]), ("working", 0.4))

    def test_the_delete_is_proven_by_the_lookup_reading_canceled(self):
        t, fake = self._t([(200, _held_lookup()), (200, CANCELED_LOOKUP)],
                          routes=[SEARCH_GLDM, DELETE_202])
        with mock.patch("time.sleep"):
            self.assertIs(t.cancel_order("383459788"), True)
        kinds = [c[0] for c in fake.calls]
        self.assertEqual(kinds, ["GET", "DELETE", "GET"])
        d = self._deletes(fake)[0]
        self.assertIn("/api/v3/trading/execution/demo/orders/383459788", d[1])
        self.assertIn("x-request-id", d[2]["headers"])
        self.assertNotIn("json", d[2])

    def test_a_close_order_id_is_refused_before_any_delete(self):
        t, fake = self._t(LOOKUP_404_CLOSE_ID, routes=[SEARCH_GLDM, DELETE_202])
        with self.assertLogs("bot_program.engine.etoro_client", level="ERROR") as cm:
            self.assertIs(t.cancel_order("383413813"), False)
        self.assertEqual(len(_polls(fake)), 1)
        self.assertEqual(self._deletes(fake), [])
        self.assertTrue(any("383413813" in line for line in cm.output))

    def test_an_unreadable_gate_sends_nothing(self):
        t, fake = self._t((500, {}), routes=[SEARCH_GLDM, DELETE_202])
        with mock.patch("time.sleep"):
            self.assertIs(t.cancel_order("383459788"), False)
        self.assertEqual(self._deletes(fake), [])

    def test_an_already_terminal_order_is_not_deleted(self):
        """3 filled, 4/10 refused: nothing to cancel; 7/8/9: the lookup IS the
        proof. Status 5 is OPEN and is not here."""
        for body, expect in (((200, _measured_lookup()), False),
                             ((200, REJECTED_720), False),
                             ((200, _lookup(10)), False),
                             ((200, CANCELED_LOOKUP), True),
                             ((200, _lookup(8)), True),
                             ((200, _lookup(9, units=0.4)), True)):
            t, fake = self._t(body, routes=[SEARCH_GLDM, DELETE_202])
            with mock.patch("time.sleep"):
                self.assertIs(t.cancel_order("383459788"), expect)
            self.assertEqual(self._deletes(fake), [], str(body[1].get("status")))

    def test_a_delete_the_venue_refuses_is_false(self):
        """The DELETE's refusal shape is UNMEASURED; any code but 200/202/204
        is a refusal."""
        for code in (400, 404):
            t, fake = self._t((200, _held_lookup()), routes=[
                SEARCH_GLDM, ("DELETE", "/api/v3/trading/execution/demo/orders/",
                              code, {})])
            with mock.patch("time.sleep"):
                self.assertIs(t.cancel_order("383459788"), False)
            self.assertEqual(len(self._deletes(fake)), 1)

    def test_an_unproven_delete_is_never_true(self):
        """After a 202 only a lookup reading 7/8/9 is True; a held reading, a
        fill in the race, an unreadable body (id 0) and a refusal are False;
        every proof read failing is None."""
        held = (200, _held_lookup())
        for proofs in ([held, held], [held, (200, _measured_lookup(order_id=383459788))],
                       [held, (200, {"status": {"id": 0}})],
                       [held, (200, REJECTED_720)]):
            t, fake = self._t(proofs, routes=[SEARCH_GLDM, DELETE_202])
            with mock.patch("time.sleep"), \
                    self.assertLogs("bot_program.engine.etoro_client",
                                    level="ERROR") as cm:
                self.assertIs(t.cancel_order("383459788"), False)
            self.assertTrue(any("not proven" in line for line in cm.output))
        t, fake = self._t([held, (500, {})], routes=[SEARCH_GLDM, DELETE_202])
        with mock.patch("time.sleep"):
            self.assertIsNone(t.cancel_order("383459788"))
        self.assertEqual(len(self._deletes(fake)), 1)

    def test_a_delete_that_raises_is_still_proven_by_the_lookup(self):
        import requests
        t, fake = self._t([(200, _held_lookup()), (200, CANCELED_LOOKUP)],
                          routes=[SEARCH_GLDM])
        real_hit = fake._hit

        def hit(method, url, **k):
            if method == "DELETE":
                raise requests.ConnectionError("reset")
            return real_hit(method, url, **k)

        fake._hit = hit
        with mock.patch("time.sleep"):
            self.assertIs(t.cancel_order("383459788"), True)
        t, fake = self._t([(200, _held_lookup()), (500, {})], routes=[SEARCH_GLDM])
        real_hit = fake._hit

        def hit2(method, url, **k):
            if method == "DELETE":
                raise requests.ConnectionError("reset")
            return real_hit(method, url, **k)

        fake._hit = hit2
        with mock.patch("time.sleep"):
            self.assertIsNone(t.cancel_order("383459788"))

    def test_the_live_delete_spelling_is_the_measured_one(self):
        """It raised (LookupError, an empty _V3_EXEC_REAL_SEG) until the
        real DELETE was MEASURED on 2026-09-26 22:03:11 UTC: no segment,
        202, then 7 Canceled (tests/test_real_account_measured.py pins the
        sitting and cancel_order on a real client). The demo spelling is
        unchanged."""
        live, fake = _client([], env="live")
        self.assertEqual(EtoroTrader._V3_EXEC_REAL_SEG, {"orders": ""})
        self.assertEqual(live._v3_exec_order("1596774177"),
                         f"{BASE}/api/v3/trading/execution/orders/1596774177")
        self.assertEqual(fake.calls, [])
        demo, _ = _client([])
        self.assertEqual(demo._v3_exec_order("383459788"),
                         f"{BASE}/api/v3/trading/execution/demo/orders/383459788")

    def test_a_held_order_pledges_margin_and_frozen_cash(self):
        t, _ = _client([("GET", "/aggregate-portfolio", 200, HELD_TOTALS)])
        self.assertEqual(t.margin_cells()["used_margin"], 42.5)
        self.assertEqual(t._totals(t.account())["accountFrozenCash"], 42.5)

    def test_a_partially_filled_order_is_open_and_its_withdrawal_is_proven_by_nine(self):
        """5 and 9 have met no key: the public table, kept as a belief."""
        t, fake = self._t([(200, _lookup(5, units=0.4)), (200, _lookup(9, units=0.4))],
                          routes=[SEARCH_GLDM, DELETE_202])
        with mock.patch("time.sleep"):
            self.assertIs(t.cancel_order("383459788"), True)
        self.assertEqual(len(self._deletes(fake)), 1)
        t, fake = self._t((200, _lookup(5, units=0.4)),
                          routes=[SEARCH_GLDM, DELETE_202])
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.engine.etoro_client", level="ERROR"):
            self.assertIs(t.cancel_order("383459788"), False)
        self.assertEqual(len(self._deletes(fake)), 1)


# ── ELIGIBILITY, MEASURED 2026-09-23 14:5x-15:1x UTC, both worlds, the
# operator's one pair (deploy/ETORO_DEPARTURE.md §4 D2c-0; the sitting's
# notes: scratchpad etoro_measured_2026-09-23.md §9-§10). NO byte-literal
# body was printed that day, so the rows below are COMPOSED from the
# printed KEY LIST — {"currency": "usd", "eligibilities": [{instrumentId,
# symbol, minPositionExposure, maxUnitsPerOrder, allowOpenPosition,
# requiresW8Ben, unitsQuantityType, orderFillBehaviorType,
# allowedOrderQuantityType, tradeUnitType, leverageConfigs:
# [{settlementType, direction, leverageValues, minPositionAmount,
# maxStopLossPercentage, ...}]}]} — and the printed VALUES. A key whose
# value was NOT printed (the stop band of every levered entry, an ETF's
# maxUnitsPerOrder) is LEFT OUT, so the accessor answers None and never a
# number nobody read. Ids: BTC 100000 was printed; 1001 (AAPL) and 3190
# (GLDM) are this file's /search fixtures; 1002 (EURUSD) is a fixture id
# — the forex ids were not printed. The LIVE lists are the narrower ones
# (stocks 5 vs 20, forex 30 vs 400): a demo route carries the LIVE list
# unless the demo list was printed exactly (stocks). ─────────────────────


def _clear_eligibility():
    """etoro_client._ELIGIBILITY is MODULE-level, keyed (world, id) per UTC
    day, and SEARCH_AAPL hands every test id 1001: without this in setUp
    AND tearDown the cache tests pass or fail by alphabetical order."""
    from bot_program.engine import etoro_client
    etoro_client._ELIGIBILITY.clear()
    # AND THE VENUE'S HEALTH (2026-10-05): the adapter notes every 429, 5xx
    # and transport failure of a fake wire on the Django cache (LocMem in
    # tests, kept across tests in one process), and three inside three
    # minutes hold every later eToro entry in the same process with
    # skips.VENUE_SICK.
    from bot_program import venue_health
    venue_health.reset()


def _lev(settlement, direction, values, *, max_sl=None, min_amount=10):
    """One leverageConfigs entry, the printed keys only; the stop band
    rides only where it was printed (the 1x entries: 100; stock CFD: 50)."""
    c = {"settlementType": settlement, "direction": direction,
         "leverageValues": list(values), "minPositionAmount": min_amount}
    if max_sl is not None:
        c["maxStopLossPercentage"] = max_sl
    return c


def _elig_row(iid, symbol, configs, *, min_exposure=10, max_units=None,
              allow_open=True, w8=True, units="fractional"):
    """One eligibilities[] row. maxUnitsPerOrder rides only when printed."""
    row = {"instrumentId": iid, "symbol": symbol,
           "minPositionExposure": min_exposure,
           "allowOpenPosition": allow_open, "requiresW8Ben": w8,
           "unitsQuantityType": units, "orderFillBehaviorType": "bestEffort",
           "allowedOrderQuantityType": "all", "tradeUnitType": "units",
           "leverageConfigs": list(configs)}
    if max_units is not None:
        row["maxUnitsPerOrder"] = max_units
    return row


def _elig_route(rows, world="demo", status=200):
    """The POST route of ONE world. "/info/demo/eligibility" is not a
    substring of "/info/eligibility" and vice versa, so a fake session
    routes the two worlds apart (the same pair answers both)."""
    sub = "/info/demo/eligibility" if world == "demo" else "/info/eligibility"
    return ("POST", sub, status,
            {"currency": "usd", "eligibilities": list(rows)})


# STOCKS (AAPL META MSFT AMZN TSLA NVDA GOOGL): real/long [1] maxSL 100
# minAmt 10; cfd/long LIVE [2,5] maxSL 50; cfd/short LIVE [1,2,5] maxSL 50;
# DEMO cfd/long [2,5,10,20], cfd/short [1,2,5,10,20]; minPositionExposure
# 10 USD; W8Ben required; maxUnitsPerOrder per symbol (AAPL 6151).
ROW_AAPL_LIVE = _elig_row(1001, "AAPL", [
    _lev("real", "long", [1], max_sl=100),
    _lev("cfd", "long", [2, 5], max_sl=50),
    _lev("cfd", "short", [1, 2, 5], max_sl=50)], max_units=6151)
ROW_AAPL_DEMO = _elig_row(1001, "AAPL", [
    _lev("real", "long", [1], max_sl=100),
    _lev("cfd", "long", [2, 5, 10, 20], max_sl=50),
    _lev("cfd", "short", [1, 2, 5, 10, 20], max_sl=50)], max_units=6151)
# ETFs (GLDM SLV USO UNG WEAT): NO real settlement — cfd/long [1] maxSL 100
# AND cfd/long [2,5] (band unprinted), cfd/short [1,2,5]; minExposure 10;
# W8 True; maxUnitsPerOrder unprinted. So a 1x long is a CFD (D2 measured
# its overnight fee).
ROW_GLDM_LIVE = _elig_row(3190, "GLDM", [
    _lev("cfd", "long", [1], max_sl=100),
    _lev("cfd", "long", [2, 5]),
    _lev("cfd", "short", [1, 2, 5])])
# FOREX (EURUSD GBPUSD ...): cfd only; minPositionExposure 1000 USD, minAmt
# 25; cfd/long [1] maxSL 100 AND [2,5,10,20,30]; cfd/short
# [1,2,5,10,20,30]; W8 False; maxUnitsPerOrder EURUSD 3,805,935; DEMO up
# to 400 (unprinted exactly, so the demo route carries the LIVE list).
ROW_EURUSD_LIVE = _elig_row(1002, "EURUSD", [
    _lev("cfd", "long", [1], max_sl=100, min_amount=25),
    _lev("cfd", "long", [2, 5, 10, 20, 30], min_amount=25),
    _lev("cfd", "short", [1, 2, 5, 10, 20, 30], min_amount=25)],
    min_exposure=1000, max_units=3805935, w8=False)
# CRYPTO (BTC 100000): real/long [1] maxSL 100 minAmt 10; LIVE cfd/short
# [1,2], cfd/long [2]; minPositionExposure 10; maxUnitsPerOrder 41; W8
# False; DEMO up to 20 (unprinted exactly).
ROW_BTC_LIVE = _elig_row(100000, "BTC", [
    _lev("real", "long", [1], max_sl=100),
    _lev("cfd", "long", [2]),
    _lev("cfd", "short", [1, 2])], max_units=41, w8=False)

SEARCH_EURUSD = ("GET", "/market-data/search", 200,
                 [{"instrumentId": 1002, "internalSymbolFull": "EURUSD"}])
# /search for BTCUSD found nothing on 2026-09-23; BTC answered 100000. The
# adapter asks for BTC when the platform says BTCUSD (VENUE_SPELLING,
# 2026-09-26), so this fake — matched on the url, params ignored — answers
# exactly the spelling it is asked for; the lone-result rule is gone.
SEARCH_BTC = ("GET", "/market-data/search", 200,
              [{"instrumentId": 100000, "internalSymbolFull": "BTC"}])
ELIG_AAPL = _elig_route([ROW_AAPL_DEMO])                 # demo, the default
ELIG_AAPL_LIVE = _elig_route([ROW_AAPL_LIVE], world="live")
ELIG_BTC = _elig_route([ROW_BTC_LIVE])


class TheEligibilityReadTests(SimpleTestCase):
    """EtoroTrader.eligibility and the accessors beside it, over a fake
    wire, in the shapes MEASURED 2026-09-23 (the fixture block above says
    what was printed and what is composed). ONE POST per (world,
    instrument) per UTC day once read — an unread row costs one POST per
    ask; THREE STATES behind a None (read / absent /
    error); the LIVE list readable from a demo instance; the
    leverage-keyed accessors take the UNION across the two entries one
    (settlement, direction) pair carries [FIX 1]; settlement_for is None
    on an unread row — unknown, never free [GAP 6]."""

    def setUp(self):
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    @staticmethod
    def _posts(fake):
        return [c for c in fake.calls if c[0] == "POST"]

    def test_the_url_puts_the_segment_after_info(self):
        """MEASURED 2026-09-23: info/eligibility 200 live,
        info/demo/eligibility 200 demo, trading/demo/info/eligibility 404
        — the last is what _v2() composes, so _v2_info is its own rule."""
        t, _ = _client([])
        self.assertEqual(t._v2_info("eligibility"),
                         BASE + "/api/v2/trading/info/demo/eligibility")
        self.assertEqual(t._v2_info("eligibility", "live"),
                         BASE + "/api/v2/trading/info/eligibility")
        live, _ = _client([], env="live")
        self.assertEqual(live._v2_info("eligibility"),
                         BASE + "/api/v2/trading/info/eligibility")
        self.assertEqual(live._v2_info("eligibility", "demo"),
                         BASE + "/api/v2/trading/info/demo/eligibility")
        self.assertEqual(t._v2("info/eligibility"),
                         BASE + "/api/v2/trading/demo/info/eligibility",
                         "the measured 404, kept as what _v2 composes")
        self.assertNotEqual(t._v2("info/eligibility"),
                            t._v2_info("eligibility"))

    def test_the_body_the_headers_and_one_post_per_day(self):
        t, fake = _client([SEARCH_AAPL, ELIG_AAPL])
        row = t.eligibility("AAPL")
        self.assertEqual(row["symbol"], "AAPL")
        posts = self._posts(fake)
        self.assertEqual(len(posts), 1)
        _m, url, kw = posts[0]
        self.assertTrue(url.endswith("/api/v2/trading/info/demo/eligibility"),
                        url)
        self.assertEqual(kw["json"], {"instrumentIds": [1001]})
        uuid.UUID(kw["headers"]["x-request-id"])
        self.assertEqual(kw["timeout"], t.timeout)
        self.assertIs(t.eligibility("AAPL"), row, "the same-day row")
        self.assertEqual(len(self._posts(fake)), 1,
                         "a second POST for a same-day row")
        self.assertEqual(row["_world"], "demo")
        self.assertEqual(row["_currency"], "usd")
        self.assertEqual(t.eligibility_state("AAPL"), "read")
        self.assertEqual(len(self._posts(fake)), 1)

    def test_a_fresh_client_reads_the_module_cache(self):
        """The router builds a fresh EtoroTrader per call: the second
        instance costs a /search GET (its own id map) and NO POST."""
        t, _fake = _client([SEARCH_AAPL, ELIG_AAPL])
        t.eligibility("AAPL")
        t2, fake2 = _client([SEARCH_AAPL])
        self.assertEqual(t2.min_notional("AAPL"), 10.0)
        self.assertEqual(self._posts(fake2), [])
        self.assertEqual(t2.eligibility_state("AAPL"), "read")

    def test_a_stale_day_is_asked_again(self):
        from datetime import datetime, timedelta, timezone as _tz

        from bot_program.engine import etoro_client
        t, fake = _client([SEARCH_AAPL, ELIG_AAPL])
        yesterday = datetime.now(_tz.utc).date() - timedelta(days=1)
        etoro_client._ELIGIBILITY[("demo", 1001)] = (yesterday,
                                                    {"symbol": "STALE"})
        self.assertEqual(t.eligibility("AAPL")["symbol"], "AAPL")
        self.assertEqual(len(self._posts(fake)), 1)

    def test_the_cache_key_carries_the_world(self):
        t, fake = _client([SEARCH_AAPL, ELIG_AAPL, ELIG_AAPL_LIVE])
        demo = t.eligibility("AAPL")
        live = t.eligibility("AAPL", world="live")
        urls = [c[1] for c in self._posts(fake)]
        self.assertEqual(len(urls), 2, urls)
        self.assertTrue(urls[0].endswith("/info/demo/eligibility"), urls)
        self.assertTrue(urls[1].endswith("/api/v2/trading/info/eligibility"),
                        urls)
        self.assertEqual((demo["_world"], live["_world"]), ("demo", "live"))
        t.eligibility("AAPL", world="live")
        t.eligibility("AAPL")
        self.assertEqual(len(self._posts(fake)), 2)
        self.assertEqual(t.eligibility_state("AAPL", world="live"), "read")

    def test_a_wider_demo_list_never_leaks_into_live(self):
        """DEMO IS MORE PERMISSIVE THAN LIVE (stocks 20 vs 5): the
        leverage-keyed accessors default to the LIVE world, and a demo
        instance reads it through the same pair."""
        t, _ = _client([SEARCH_AAPL, ELIG_AAPL, ELIG_AAPL_LIVE])
        self.assertEqual(t.leverage_values("AAPL", "BUY", "cfd",
                                           world="demo"), [2, 5, 10, 20])
        self.assertEqual(t.leverage_values("AAPL", "BUY", "cfd"), [2, 5],
                         "the default world is LIVE")
        self.assertEqual(t.leverage_values("AAPL", "BUY", "cfd",
                                           world="live"), [2, 5])
        self.assertEqual(t.leverage_values("AAPL", "SELL", "cfd",
                                           world="live"), [1, 2, 5])
        self.assertEqual(t.leverage_values("AAPL", "BUY", "real",
                                           world="live"), [1])
        self.assertIsNone(t.leverage_values("AAPL", "SELL", "real",
                                            world="live"))
        self.assertEqual(t.max_stop_loss_pct("AAPL", "BUY", "cfd", 2,
                                             world="live"), 50.0)
        self.assertEqual(t.max_stop_loss_pct("AAPL", "BUY", "real", 1,
                                             world="live"), 100.0)
        self.assertIsNone(t.max_stop_loss_pct("AAPL", "BUY", "cfd", 10,
                                              world="live"),
                          "10x is on the DEMO list only")

    def test_a_demo_only_wire_asked_for_live_raises_and_never_answers_the_demo_list(self):
        """Only the DEMO route answers. The LIVE ask — the default of every
        leverage-keyed accessor — meets an unrouted POST (the fake's bare
        200 {}) and RAISES on the no-list rule: the demo list [2, 5, 10,
        20] is never answered for live, and nothing is cached under live
        (the demo row stays, read once)."""
        from bot_program.engine import etoro_client
        t, fake = _client([SEARCH_AAPL, ELIG_AAPL])
        self.assertEqual(t.eligibility_state("AAPL"), "read")
        with self.assertRaises(LookupError) as caught:
            t.leverage_values("AAPL", "BUY", "cfd")
        self.assertIn("live", str(caught.exception))
        with self.assertRaises(LookupError):
            t.settlement_for("AAPL", "BUY", 2, world="live")
        self.assertEqual(set(etoro_client._ELIGIBILITY), {("demo", 1001)})
        urls = [c[1] for c in self._posts(fake)]
        self.assertEqual(len(urls), 3, urls)
        self.assertTrue(urls[1].endswith("/api/v2/trading/info/eligibility"),
                        urls)
        self.assertEqual(t.leverage_values("AAPL", "BUY", "cfd",
                                           world="demo"), [2, 5, 10, 20])
        self.assertEqual(len(self._posts(fake)), 3, "the demo row is cached")

    def test_a_200_without_the_id_is_absent_for_the_day(self):
        """The venue answered and listed no row for this id: ABSENT, cached
        for the UTC day, every accessor None, no second POST."""
        t, fake = _client([SEARCH_AAPL, _elig_route([ROW_GLDM_LIVE])])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="WARNING"):
            self.assertIsNone(t.eligibility("AAPL"))
        self.assertEqual(t.eligibility_state("AAPL"), "absent")
        self.assertIsNone(t.min_notional("AAPL"))
        self.assertIsNone(t.unit_type("AAPL"))
        self.assertIsNone(t.takes_fractional_units("AAPL"))
        self.assertIsNone(t.allow_open_position("AAPL"))
        self.assertIsNone(t.settlement_for("AAPL", "BUY", 1))
        self.assertIsNone(t.leverage_values("AAPL", "BUY", "cfd",
                                            world="demo"))
        self.assertEqual(len(self._posts(fake)), 1,
                         "an absent row was asked again the same day")

    def test_a_non_200_is_an_error_not_cached_and_asked_again(self):
        """429 included: nothing is cached, the next call asks again, and
        every accessor is None — unmeasured, never whole and never free.
        A 5xx is asked once more within the same call (READ_RETRIES,
        2026-10-05); a 429 and a 403 are not."""
        from bot_program.engine import etoro_client
        from bot_program.engine.etoro_client import READ_RETRIES
        for status in (429, 500, 403):
            with self.subTest(status=status):
                _clear_eligibility()
                t, fake = _client([SEARCH_AAPL,
                                   _elig_route([], status=status)])
                with self.assertLogs("bot_program.engine.etoro_client",
                                     level="WARNING"), \
                        mock.patch("time.sleep"):
                    self.assertIsNone(t.eligibility("AAPL"))
                self.assertEqual(etoro_client._ELIGIBILITY, {})
                with mock.patch("time.sleep"):
                    self.assertEqual(t.eligibility_state("AAPL"), "error")
                per_ask = 1 + READ_RETRIES if status >= 500 else 1
                self.assertEqual(len(self._posts(fake)), 2 * per_ask,
                                 "the second call must ask again")
                self.assertIsNone(t.takes_fractional_units("AAPL"))
                self.assertIsNone(t.settlement_for("AAPL", "BUY", 1))
                self.assertIsNone(t.min_notional("AAPL"))

    def test_a_200_without_the_list_raises_and_caches_nothing(self):
        """The ticker() rule: a 200 whose body has no `eligibilities`
        list is a shape never seen answer — unmeasured, not empty."""
        from bot_program.engine import etoro_client
        t, _ = _client([SEARCH_AAPL,
                        ("POST", "/info/demo/eligibility", 200,
                         {"currency": "usd", "items": []})])
        with self.assertRaises(LookupError) as caught:
            t.eligibility("AAPL")
        self.assertIn("['currency', 'items']", str(caught.exception))
        self.assertIn("eligibilities", str(caught.exception))
        self.assertEqual(etoro_client._ELIGIBILITY, {})
        with self.assertRaises(LookupError):
            t.eligibility_state("AAPL")
        t2, _ = _client([SEARCH_AAPL,
                         ("POST", "/info/demo/eligibility", 200,
                          [ROW_AAPL_LIVE])])
        with self.assertRaises(LookupError):
            t2.eligibility("AAPL")
        self.assertEqual(etoro_client._ELIGIBILITY, {})

    def test_an_unknown_spelling_raises_before_any_post(self):
        t, fake = _client([("GET", "/market-data/search", 200, [])])
        with self.assertRaises(LookupError):
            t.eligibility("NOPE")
        with self.assertRaises(LookupError):
            t.eligibility_state("NOPE")
        self.assertEqual(self._posts(fake), [])

    def test_the_rows_symbol_confirms_the_spelling(self):
        """The row's `symbol` is written to _venue_spelling: the NAME
        confirmation a lone /search result lacks (WHEAT -> WHEAT.FUT 97,
        doc §10). Since 2026-09-26 the platform's WHEATUSD reaches id 97
        through VENUE_SPELLING — the lone answer to WHEAT is refused."""
        t, _ = _client([SEARCH_AAPL, ELIG_AAPL])
        t.instrument_id("AAPL")
        self.assertEqual(t._venue_spelling[1001], "AAPL")
        t.eligibility("AAPL")
        self.assertEqual(t._venue_spelling[1001], "AAPL")
        _clear_eligibility()
        t2, _ = _client([
            ("GET", "/market-data/search", 200,
             [{"instrumentId": 97, "internalSymbolFull": "WHEAT.FUT"}]),
            _elig_route([_elig_row(
                97, "WHEAT.FUT",
                [_lev("cfd", "long", [1], max_sl=100, min_amount=25)],
                min_exposure=1000, w8=False)])])
        self.assertEqual(t2.instrument_id("WHEATUSD"), 97)
        self.assertEqual(t2.eligibility("WHEATUSD")["symbol"], "WHEAT.FUT")
        self.assertEqual(t2._venue_spelling[97], "WHEAT.FUT")
        self.assertEqual(t2.min_notional("WHEATUSD"), 1000.0)

    def test_the_row_accessors_answer_the_measured_values(self):
        t, _ = _client([SEARCH_AAPL, ELIG_AAPL])
        self.assertEqual(t.unit_type("AAPL"), "fractional")
        self.assertEqual(t.min_notional("AAPL"), 10.0)
        self.assertIsInstance(t.min_notional("AAPL"), float)
        self.assertEqual(t.max_units_per_order("AAPL"), 6151.0)
        self.assertIs(t.allow_open_position("AAPL"), True)
        self.assertIs(t.requires_w8ben("AAPL"), True)
        _clear_eligibility()
        e, _ = _client([SEARCH_EURUSD, _elig_route([ROW_EURUSD_LIVE])])
        self.assertEqual(e.min_notional("EURUSD"), 1000.0)
        self.assertEqual(e.max_units_per_order("EURUSD"), 3805935.0)
        self.assertIs(e.requires_w8ben("EURUSD"), False)
        _clear_eligibility()
        g, _ = _client([SEARCH_GLDM, _elig_route([ROW_GLDM_LIVE])])
        self.assertIsNone(g.max_units_per_order("GLDM"),
                          "unprinted for ETFs: None, never a number")
        self.assertEqual(g.min_notional("GLDM"), 10.0)
        self.assertIs(g.requires_w8ben("GLDM"), True)

    def test_a_floor_typed_in_another_currency_raises_never_scales(self):
        """MEASURED 2026-09-23: the body's `currency` read "usd" in both
        worlds and the money floor is divided by a USD price. A body typed
        in anything else would scale the floor silently, so min_notional
        RAISES naming the currency (unmeasured, the ticker() rule); the
        currency-free accessors on the same row still answer, one POST;
        base._venue_size_floor reads the raise as unmeasured, the
        currency in its reason, never a number. A body naming no currency
        raises too."""
        from bot_program.asset_engine.base import AssetBot
        t, fake = _client([SEARCH_EURUSD,
                           ("POST", "/info/demo/eligibility", 200,
                            {"currency": "eur",
                             "eligibilities": [ROW_EURUSD_LIVE]})])
        with self.assertRaises(LookupError) as caught:
            t.min_notional("EURUSD")
        self.assertIn("eur", str(caught.exception))
        self.assertIn("not usd", str(caught.exception))
        self.assertEqual(t.eligibility_state("EURUSD"), "read")
        self.assertEqual(t.max_units_per_order("EURUSD"), 3805935.0)
        self.assertIs(t.takes_fractional_units("EURUSD"), True)
        self.assertEqual(len(self._posts(fake)), 1)
        floor, why = AssetBot._venue_size_floor(t, "EURUSD", price=1.08)
        self.assertIsNone(floor)
        self.assertIn("eur", why)
        self.assertIn("LookupError", why)
        _clear_eligibility()
        bare, _ = _client([SEARCH_EURUSD,
                           ("POST", "/info/demo/eligibility", 200,
                            {"eligibilities": [ROW_EURUSD_LIVE]})])
        with self.assertRaises(LookupError) as caught2:
            bare.min_notional("EURUSD")
        self.assertIn("no currency", str(caught2.exception))

    def test_fractional_is_three_states_off_unitsquantitytype(self):
        t, fake = _client([SEARCH_AAPL, ELIG_AAPL])
        self.assertIs(t.takes_fractional_units("AAPL"), True)
        self.assertEqual(len(self._posts(fake)), 1)
        self.assertIs(t.takes_fractional_units("AAPL"), True)
        self.assertEqual(len(self._posts(fake)), 1, "one POST per day")
        _clear_eligibility()
        w, _ = _client([SEARCH_AAPL, _elig_route([
            _elig_row(1001, "AAPL", [], units="whole")])])
        self.assertIs(w.takes_fractional_units("AAPL"), False)
        _clear_eligibility()
        bare = _elig_row(1001, "AAPL", [])
        del bare["unitsQuantityType"]
        n, _ = _client([SEARCH_AAPL, _elig_route([bare])])
        self.assertIsNone(n.takes_fractional_units("AAPL"),
                          "the key absent: None, never a guess")
        _clear_eligibility()
        u, _ = _client([SEARCH_AAPL, _elig_route([], status=503)])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="WARNING"):
            self.assertIsNone(u.takes_fractional_units("AAPL"))

    def test_settlement_for_is_read_never_free(self):
        """"real" only for a 1x long where a real/long entry exists; "cfd"
        wherever a cfd entry exists for the direction; None on a row with
        neither AND on an unread row (unknown is not free). B: eToro's
        own assignment when the order body omits settlementType is
        measured once (GLDM 1x -> CFD, D2), consistent with this."""
        t, _ = _client([SEARCH_AAPL, ELIG_AAPL])
        self.assertEqual(t.settlement_for("AAPL", "BUY", 1), "real")
        self.assertEqual(t.settlement_for("AAPL", "BUY", None), "real")
        self.assertEqual(t.settlement_for("AAPL", "BUY", 1.0), "real")
        self.assertEqual(t.settlement_for("AAPL", "BUY", 2), "cfd")
        self.assertEqual(t.settlement_for("AAPL", "SELL", 1), "cfd")
        _clear_eligibility()
        g, _ = _client([SEARCH_GLDM, _elig_route([ROW_GLDM_LIVE])])
        self.assertEqual(g.settlement_for("GLDM", "BUY", 1), "cfd",
                         "an ETF has no real settlement: a 1x long is a "
                         "CFD (D2 measured its fee)")
        _clear_eligibility()
        e, _ = _client([SEARCH_EURUSD, _elig_route([ROW_EURUSD_LIVE])])
        self.assertEqual(e.settlement_for("EURUSD", "BUY", 10), "cfd")
        self.assertEqual(e.settlement_for("EURUSD", "SELL", 1), "cfd")
        _clear_eligibility()
        u, _ = _client([SEARCH_AAPL, _elig_route([], status=503)])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="WARNING"):
            self.assertIsNone(u.settlement_for("AAPL", "BUY", 1),
                              "unread is unknown, never free")
        _clear_eligibility()
        none, _ = _client([SEARCH_AAPL,
                           _elig_route([_elig_row(1001, "AAPL", [])])])
        self.assertIsNone(none.settlement_for("AAPL", "BUY", 1))

    def test_the_leverage_keyed_accessors_take_the_union_of_a_pairs_entries(self):
        """[FIX 1] ONE (settlementType, direction) pair carries TWO
        entries on ETFs, forex, indices and commodities — cfd/long [1]
        maxSL 100 AND cfd/long [2,5] — so a single-entry pick would
        answer [1] or [2,5] by response order. The list is the UNION; the
        band is the entry that CARRIES the multiplier; an unprinted band
        is None."""
        t, _ = _client([SEARCH_GLDM,
                        _elig_route([ROW_GLDM_LIVE], world="live")])
        self.assertEqual(len(t._lev_configs("GLDM", "BUY", "cfd",
                                            world="live")), 2)
        self.assertEqual(t.leverage_values("GLDM", "BUY", "cfd",
                                           world="live"), [1, 2, 5])
        self.assertEqual(t.max_stop_loss_pct("GLDM", "BUY", "cfd", 1,
                                             world="live"), 100.0)
        self.assertIsNone(t.max_stop_loss_pct("GLDM", "BUY", "cfd", 5,
                                              world="live"),
                          "the levered band was not printed: None, "
                          "never 100")
        self.assertIsNone(t._lev_config_for("GLDM", "BUY", "cfd", 3,
                                            world="live"))
        self.assertIsNone(t.max_stop_loss_pct("GLDM", "BUY", "cfd", 3,
                                              world="live"))
        self.assertIsNone(t.min_stop_loss_pct("GLDM", "BUY", "cfd", 1,
                                              world="live"))
        self.assertEqual(t.min_amount("GLDM", "BUY", "cfd", 1,
                                      world="live"), 10.0)
        self.assertEqual(t.leverage_values("GLDM", "SELL", "cfd",
                                           world="live"), [1, 2, 5])
        self.assertIsNone(t.leverage_values("GLDM", "BUY", "real",
                                            world="live"))
        _clear_eligibility()
        e, _ = _client([SEARCH_EURUSD,
                        _elig_route([ROW_EURUSD_LIVE], world="live")])
        self.assertEqual(e.leverage_values("EURUSD", "BUY", "cfd",
                                           world="live"),
                         [1, 2, 5, 10, 20, 30])
        self.assertEqual(e.max_stop_loss_pct("EURUSD", "BUY", "cfd", 1,
                                             world="live"), 100.0)
        self.assertIsNone(e.max_stop_loss_pct("EURUSD", "BUY", "cfd", 30,
                                              world="live"))
        self.assertEqual(e.min_amount("EURUSD", "BUY", "cfd", 30,
                                      world="live"), 25.0)
        self.assertIsNone(e._lev_config_for("EURUSD", "BUY", "cfd", 400,
                                            world="live"),
                          "400 is the DEMO ceiling, never on the LIVE list")


class ConsumerKeyTests(SimpleTestCase):
    """The keys the adapter answers are the keys the engine reads — read out
    of the consumers themselves (the tests/test_saxo_client.py rule)."""

    def test_the_result_keys_are_the_ones_base_reads(self):
        import inspect
        from pathlib import Path
        from django.conf import settings
        from bot_program.asset_engine.base import AssetBot
        entry = inspect.getsource(AssetBot.execute_entry)
        for key in ('"orderId"', '"status"', '"executedQty"', '"avgPrice"',
                    '"refusal"', '"venueStopLoss"', '"working"',
                    '"pollFailed"', '"protectedOnFill"',
                    '"protectiveTradeId"'):
            self.assertIn(key, entry, key)
        stamps = inspect.getsource(AssetBot.venue_stamps)
        self.assertIn('"positionId"', stamps)
        self.assertIn('"broker_position_id"', stamps)
        manual = (Path(settings.BASE_DIR) / "bot_program"
                  / "manual_trade.py").read_text(encoding="utf-8")
        self.assertIn("broker_order_id=", manual)
        self.assertIn('"protectiveTradeId"', manual)
        # C0 (2026-09-24): the hand lane stamps the carrier, its world and
        # the close handle with the bots' own rule, off the same client
        # and fill
        self.assertIn("venue_stamps(client, res)", manual)
        # D3b put a live-segment caveat on the TAKE TRADE note (the real
        # DELETE was unmeasured); since the real DELETE answered as the
        # demo one did (2026-09-26) the note is one promise on both
        # worlds and the caveat is GONE. The note lives in
        # manual_trade._execute, so the file text is read
        self.assertNotIn('adapter_key(client) == "etoro" and not getattr(client, "demo", True)', manual)
        self.assertNotIn("the tick alerts daily instead of withdrawing", manual)

    def test_the_close_path_hands_the_open_order_id_and_reads_the_proof(self):
        import inspect
        from decimal import Decimal
        from pathlib import Path
        from django.conf import settings
        from bot_program import pending_closes
        base = Path(settings.BASE_DIR) / "bot_program"
        vc = (base / "engine" / "venue_close.py").read_text(encoding="utf-8")
        self.assertIn('"open_order_id" in params', vc)
        self.assertIn('getattr(trade, "broker_order_id", "")', vc)
        pc = (base / "pending_closes.py").read_text(encoding="utf-8")
        for needle in ('getattr(client, "position_state", None)',
                       "fn(oid, attempts=1, delay=0.0)",
                       'proof == "closed"', "RETRY_VENUE_PROVED_CLOSED",
                       "_note_close_blocked(", "venue_lag_window",
                       'CLOSE_SENT_AT_KEY = "close_sent_at"',
                       'proof == "open" and exposure["state"] == POS_FLAT'):
            self.assertIn(needle, pc, needle)
        self.assertIn("unattributable(trade, client,",
                      inspect.getsource(pending_closes.venue_position_state))
        ra = (base / "reconcile_asset.py").read_text(encoding="utf-8")
        for needle in ("def venue_lag_window",
                       'getattr(client, "PORTFOLIO_LAG_S", 0)',
                       "SWEEP_CLOSED_GRACE_S", "closed_at__gte"):
            self.assertIn(needle, ra, needle)
        ec = (base / "engine" / "etoro_client.py").read_text(encoding="utf-8")
        for needle in ("def position_state", "def _lookup_once",
                       "PORTFOLIO_LAG_S = 60", 'open_order_id: str = ""',
                       '{"orderId": oid}', 'out["executedQty"]',
                       'out["openOrderId"]'):
            self.assertIn(needle, ec, needle)
        self.assertNotIn('params={"referenceId": reference_id}', ec)
        self.assertEqual(pending_closes.broker_filled_qty(
            {"status": "PENDING", "executedQty": "0.0"}), Decimal(0))
        self.assertIsNone(pending_closes.broker_filled_qty(
            {"status": "PENDING"}))

    def test_the_working_entry_keys_are_the_ones_the_poller_reads(self):
        import inspect
        from pathlib import Path
        from django.conf import settings
        from bot_program.asset_engine.base import (AssetBot,
                                                   cancel_working_entry)
        poll = inspect.getsource(AssetBot._poll_working_entry)
        for needle in ('st.get("state")', 'st.get("filled")',
                       'st.get("avgPrice")', "st.get('refusal')", "venue=st",
                       "venue=after or st", "if not cancel_working_entry("):
            self.assertIn(needle, poll, needle)
        fin = inspect.getsource(AssetBot._finish_working_entry)
        for needle in ("venue_stamps(client, venue)", '"venueStopLoss"',
                       '"positionId"', "protective_trade_id",
                       "venue_stop_unread", "stop_rewritten_by_venue",
                       'adapter_key(client) == "etoro"'):
            self.assertIn(needle, fin, needle)
        cancel = inspect.getsource(cancel_working_entry)
        self.assertIn("sent is False", cancel)
        self.assertIn('state != "dead"', cancel)
        base = Path(settings.BASE_DIR) / "bot_program"
        pc = (base / "pending_closes.py").read_text(encoding="utf-8")
        self.assertIn("cancelled is False or cancelled is None", pc)
        ec = (base / "engine" / "etoro_client.py").read_text(encoding="utf-8")
        for needle in ("def order_status", "def cancel_order",
                       "def _v3_exec_order", "_V3_EXEC_REAL_SEG",
                       "self._await_fill(oid)", "in (7, 8, 9)", '"refusal"'):
            self.assertIn(needle, ec, needle)
        capf = (base / "engine" / "capabilities.py").read_text(encoding="utf-8")
        self.assertIn('"execution", "orders", "brackets"', capf)


class TheVenueSpellingTests(SimpleTestCase):
    """VENUE_SPELLING and FIX 6 (2026-09-26). The platform spelling is the
    key everywhere; the adapter rewrites it for the /search param and the
    order body only. Every entry is an id /search answered on 2026-09-23
    (doc §10): BTC 100000, ETH 100001, XRP 100003, SOL 100063, 'WHEAT.FUT'
    97 (a LONE result to WHEAT), PLATINUM 40, UK100 30, FRA40 31, GER40 32,
    JPN225 36, EUSTX50 43 — and SPX500 27 as spelled, so no entry; /search
    answered nothing for BTCUSD, ETHUSD, XAUUSD, XAGUSD. A lone result
    spelled differently is refused, never adopted, and caches nothing."""

    def setUp(self):
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    @staticmethod
    def _searches(fake):
        return [c[2]["params"] for c in fake.calls if "/search" in c[1]]

    def test_the_table_is_the_measured_one(self):
        from bot_program.engine.etoro_client import (VENUE_SPELLING,
                                                     VENUE_SPELLING_UNKNOWN)
        self.assertEqual(VENUE_SPELLING, {
            "BTCUSD": "BTC", "ETHUSD": "ETH", "XRPUSD": "XRP",
            "SOLUSD": "SOL", "WHEATUSD": "WHEAT.FUT", "XPTUSD": "PLATINUM",
            "FTSE100": "UK100", "CAC40": "FRA40", "DAX40": "GER40",
            "NIKKEI225": "JPN225", "STOXX50": "EUSTX50",
            # 2026-10-01, the eligibility read by symbols
            "XAUUSD": "GOLD", "XAGUSD": "SILVER", "WTIUSD": "OIL",
            "NGUSD": "NATGAS", "HGUSD": "COPPER.FUT",
            "XPDUSD": "PALLADIUM.FUT",
            # 2026-10-04, the eligibility read by symbols, live world:
            # the eleven other catalogue cryptos; Polygon is POL at eToro
            "LTCUSD": "LTC", "ADAUSD": "ADA", "DOTUSD": "DOT",
            "LINKUSD": "LINK", "UNIUSD": "UNI", "DOGEUSD": "DOGE",
            "AAVEUSD": "AAVE", "ATOMUSD": "ATOM", "MATICUSD": "POL",
            "AVAXUSD": "AVAX", "NEARUSD": "NEAR"})
        self.assertEqual(VENUE_SPELLING_UNKNOWN, ("BRNUSD",))

    def test_the_pinned_ids_are_the_measured_ones(self):
        """2026-10-01: each id the eligibility read answered for that
        spelling (floor 1000, cfd, open). /search lists them only among
        look-alikes, so they are pinned and /search is never asked.
        2026-10-04: the eleven cryptos the same read answered (floor 10,
        fractional), pinned so a config of them never asks /search a
        dozen times a tick (HTTP 429 on the smoke)."""
        from bot_program.engine.etoro_client import VENUE_ID_PINS
        self.assertEqual(VENUE_ID_PINS, {
            "XAUUSD": 18, "XAGUSD": 19, "WTIUSD": 17, "NGUSD": 22,
            "HGUSD": 21, "XPDUSD": 91,
            "LTCUSD": 100005, "ADAUSD": 100017, "DOTUSD": 100037,
            "LINKUSD": 100040, "UNIUSD": 100041, "DOGEUSD": 100043,
            "AAVEUSD": 100044, "ATOMUSD": 100047, "MATICUSD": 100056,
            "AVAXUSD": 100085, "NEARUSD": 100337})

    def test_every_catalogue_crypto_resolves_without_search(self):
        """Every INSTRUMENTS_DATA crypto reaches eToro: the four /search
        answered on 2026-09-23 keep their /search, the eleven pinned on
        2026-10-04 resolve to their id with no request at all, and each
        reads back under its platform spelling."""
        from bot_program.engine.etoro_client import (VENUE_ID_PINS,
                                                     VENUE_SPELLING)
        from instruments.services import INSTRUMENTS_DATA
        cryptos = set(INSTRUMENTS_DATA["crypto"])
        self.assertEqual(len(cryptos), 15)
        self.assertTrue(cryptos.issubset(VENUE_SPELLING))
        pinned = {s for s in cryptos if s in VENUE_ID_PINS}
        self.assertEqual(cryptos - pinned,
                         {"BTCUSD", "ETHUSD", "XRPUSD", "SOLUSD"})
        t, fake = _client([])
        for symbol in sorted(pinned):
            self.assertEqual(t.instrument_id(symbol), VENUE_ID_PINS[symbol])
            self.assertEqual(t._symbol_for(VENUE_ID_PINS[symbol]), symbol)
            self.assertEqual(t._venue_spelling[VENUE_ID_PINS[symbol]],
                             VENUE_SPELLING[symbol])
        self.assertEqual(self._searches(fake), [], "asked /search for a pin")

    def test_a_pinned_symbol_resolves_without_search_and_reads_back(self):
        t, fake = _client([("GET", "/info/demo/portfolio", 200,
                            {"clientPortfolio": {"positions": [
                                dict(PORTFOLIO_ROW, instrumentID=18)]}})])
        self.assertEqual(t.instrument_id("XAUUSD"), 18)
        self.assertEqual(self._searches(fake), [], "asked /search for a pin")
        self.assertEqual(t._venue_spelling[18], "GOLD")
        rows = t.get_positions()
        self.assertEqual(rows[0]["symbol"], "XAUUSD")
        self.assertNotIn("symbol_unresolved", rows[0])

    def test_the_catalogue_gold_stock_never_takes_the_metals_id(self):
        """The catalogue's GOLD is Barrick Gold, a STOCK. Were /search to
        answer GOLD exactly with id 18 — eToro's metal — it is refused,
        never adopted."""
        t, _ = _client([("GET", "/market-data/search", 200,
                         [{"instrumentId": 18,
                           "internalSymbolFull": "GOLD"}])])
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("GOLD")
        self.assertIn("pinned to 'XAUUSD'", str(cm.exception))
        self.assertNotIn("GOLD", t._ids)

    def test_the_order_body_carries_etoros_spelling_for_a_pin(self):
        from bot_program.engine.etoro_client import VENUE_SPELLING
        self.assertEqual(VENUE_SPELLING["XAUUSD"], "GOLD")

    def test_every_key_is_a_catalogue_spelling_and_no_value_is_one(self):
        """The LEFT column is what configs, Instrument rows and bars carry
        (instruments.services.INSTRUMENTS_DATA); the RIGHT column must
        never be one, or a reader would meet eToro's spelling as a
        platform symbol."""
        from bot_program.engine.etoro_client import (VENUE_SPELLING,
                                                     VENUE_SPELLING_UNKNOWN)
        from instruments.services import INSTRUMENTS_DATA
        cls_of = {s: c for c, rows in INSTRUMENTS_DATA.items() for s in rows}
        self.assertEqual({k: cls_of.get(k) for k in VENUE_SPELLING}, {
            "BTCUSD": "crypto", "ETHUSD": "crypto", "XRPUSD": "crypto",
            "SOLUSD": "crypto", "WHEATUSD": "commodity",
            "XPTUSD": "commodity", "FTSE100": "index", "CAC40": "index",
            "DAX40": "index", "NIKKEI225": "index", "STOXX50": "index",
            "XAUUSD": "commodity", "XAGUSD": "commodity",
            "WTIUSD": "commodity", "NGUSD": "commodity",
            "HGUSD": "commodity", "XPDUSD": "commodity",
            "LTCUSD": "crypto", "ADAUSD": "crypto", "DOTUSD": "crypto",
            "LINKUSD": "crypto", "UNIUSD": "crypto", "DOGEUSD": "crypto",
            "AAVEUSD": "crypto", "ATOMUSD": "crypto", "MATICUSD": "crypto",
            "AVAXUSD": "crypto", "NEARUSD": "crypto"})
        # The one known collision: eToro spells the metal GOLD, and the
        # catalogue's GOLD is Barrick Gold (a stock). Guarded in
        # instrument_id (a pinned id answering another platform symbol is
        # refused) and pinned by
        # test_the_catalogue_gold_stock_never_takes_the_metals_id.
        collisions = {v for v in VENUE_SPELLING.values() if v in cls_of}
        self.assertEqual(collisions, {"GOLD"})
        self.assertEqual(cls_of["GOLD"], "stock")
        for value in VENUE_SPELLING.values():
            self.assertNotIn(value, VENUE_SPELLING, value)
        for key in VENUE_SPELLING_UNKNOWN:
            self.assertEqual(cls_of.get(key), "commodity", key)
            self.assertNotIn(key, VENUE_SPELLING, key)

    def test_btcusd_is_asked_as_btc_and_named_btcusd_on_the_way_back(self):
        t, fake = _client([SEARCH_BTC,
                           ("GET", "/info/demo/portfolio", 200,
                            {"clientPortfolio": {"positions": [
                                dict(PORTFOLIO_ROW, instrumentID=100000)]}})])
        self.assertEqual(t.instrument_id("BTCUSD"), 100000)
        self.assertEqual(t.instrument_id("btcusd"), 100000)
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "BTC"}],
                         "asked twice, or asked in the platform's spelling")
        self.assertEqual(t._ids, {"BTCUSD": 100000})
        self.assertEqual(t._symbols[100000], "BTCUSD")
        self.assertEqual(t._venue_spelling[100000], "BTC")
        rows = t.get_positions()
        self.assertEqual(rows[0]["symbol"], "BTCUSD")
        self.assertNotIn("symbol_unresolved", rows[0])

    def test_the_order_body_carries_btc_for_btcusd(self):
        """The body's `symbol` is eToro's spelling; nothing else in it
        moves. A mapped spelling on the body has met no key yet — the
        crypto proof is the first (deploy/ETORO_DEPARTURE.md §7). The
        client resolves BTC on /search BEFORE the POST (FIX 6 on the order
        path), on a client that never priced it."""
        t, fake = _client([SEARCH_BTC, POST_GLDM,
                           ("GET", "orders:lookup", 200, _lookup(3))])
        with mock.patch("time.sleep"):
            t.market_order("BTCUSD", "BUY", 1, stop_loss=80000.0,
                           take_profit=90000.0)
        body = [c for c in fake.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body["symbol"], "BTC")
        self.assertEqual(body["units"], 1.0)
        self.assertEqual(body["leverage"], 1)
        kinds = [(c[0], "/search" in c[1]) for c in fake.calls]
        self.assertLess(kinds.index(("GET", True)),
                        kinds.index(("POST", False)))
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "BTC"}])
        t2, fake2 = _client([SEARCH_GLDM, POST_GLDM,
                             ("GET", "orders:lookup", 200, _lookup(3))])
        with mock.patch("time.sleep"):
            t2.market_order("GLDM", "BUY", 1, stop_loss=82.22,
                            take_profit=87.3)
        body2 = [c for c in fake2.calls if c[0] == "POST"][0][2]["json"]
        self.assertEqual(body2["symbol"], "GLDM", "an unmapped spelling moved")

    def test_an_unmapped_spelling_is_asked_as_spelled(self):
        """SPX500 answered id 27 as spelled (doc §10): no entry, and one
        item spelled exactly as asked resolves."""
        t, fake = _client([("GET", "/market-data/search", 200,
                            [{"instrumentId": 27,
                              "internalSymbolFull": "SPX500"}])])
        self.assertEqual(t.instrument_id("SPX500"), 27)
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "SPX500"}])
        self.assertEqual(t._symbols[27], "SPX500")

    def test_the_lone_wheat_answer_is_refused_naming_both_and_the_id(self):
        """/search WHEAT answered 'WHEAT.FUT' 97 alone (doc §10). Unmapped,
        that answer is refused before any price or order: the ticker
        raises too, and no rate is ever asked."""
        t, fake = _client([("GET", "/market-data/search", 200,
                            [{"instrumentId": 97,
                              "internalSymbolFull": "WHEAT.FUT"}])])
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("WHEAT")
        self.assertIs(type(cm.exception), LookupError)
        for part in ("'WHEAT'", "'WHEAT.FUT'", "id 97", "2026-09-23"):
            self.assertIn(part, str(cm.exception))
        self.assertEqual((cm.exception.lone_id, cm.exception.lone_spelling),
                         (97, "WHEAT.FUT"))
        with self.assertRaises(LookupError):
            t.ticker("WHEAT")
        self.assertFalse([c for c in fake.calls if "/rates" in c[1]])
        self.assertEqual((t._ids, t._symbols), ({}, {}))

    def test_the_mapped_lone_answer_resolves(self):
        """WHEATUSD is asked as WHEAT.FUT and eToro's item is spelled
        exactly that: adopted under the platform spelling."""
        t, fake = _client([("GET", "/market-data/search", 200,
                            [{"instrumentId": 97,
                              "internalSymbolFull": "WHEAT.FUT"}])])
        self.assertEqual(t.instrument_id("WHEATUSD"), 97)
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "WHEAT.FUT"}])
        self.assertEqual(t._symbols[97], "WHEATUSD")
        self.assertEqual(t._venue_spelling[97], "WHEAT.FUT")

    def test_a_spelling_etoro_refused_raises_with_the_date(self):
        t, _ = _client([("GET", "/market-data/search", 200, [])])
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("BRNUSD")
        self.assertIn("'BRNUSD'", str(cm.exception))
        self.assertIn("measured 2026-09-23", str(cm.exception))
        self.assertIn("ETORO_DEPARTURE.md", str(cm.exception))
        with self.assertRaises(LookupError) as plain:
            t.instrument_id("NOPE")
        self.assertEqual(str(plain.exception),
                         "eToro knows no instrument spelled 'NOPE'")

    def test_the_eligibility_read_reaches_the_mapped_id(self):
        """The eligibility read keys on the id, so the map reaches it
        through instrument_id: BTCUSD reads the BTC row (§15: floor 10,
        maxUnitsPerOrder 41, real at 1x)."""
        t, fake = _client([SEARCH_BTC, ELIG_BTC])
        self.assertEqual(t.eligibility("BTCUSD")["symbol"], "BTC")
        self.assertEqual(t.min_notional("BTCUSD"), 10.0)
        self.assertEqual(t.max_units_per_order("BTCUSD"), 41)
        self.assertEqual(t.settlement_for("BTCUSD", "BUY", 1), "real")
        posts = [c for c in fake.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]["json"], {"instrumentIds": [100000]})
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "BTC"}])

    def test_the_five_non_usd_indices_are_mapped_with_their_currency_unread(self):
        """VENUE_QUOTE_UNMEASURED (2026-09-26): the five index CFDs the map
        resolves (doc §10: UK100 30, FRA40 31, GER40 32, JPN225 36, EUSTX50
        43) whose quote currency nobody has read. The entry gate refuses
        them (tests/test_etoro_routing.py); here, the table."""
        from bot_program.engine.etoro_client import (VENUE_QUOTE_UNMEASURED,
                                                     VENUE_SPELLING)
        self.assertEqual(VENUE_QUOTE_UNMEASURED,
                         ("FTSE100", "CAC40", "DAX40", "NIKKEI225", "STOXX50"))
        self.assertEqual([VENUE_SPELLING[k] for k in VENUE_QUOTE_UNMEASURED],
                         ["UK100", "FRA40", "GER40", "JPN225", "EUSTX50"])
        self.assertNotIn("SPX500", VENUE_QUOTE_UNMEASURED)

    def test_a_mapped_spelling_etoro_does_not_answer_names_both(self):
        """/search is asked the map's rewrite; an empty answer names the
        platform spelling AND the one asked, so nobody hunts for BTCUSD on
        eToro. Nothing is cached."""
        t, fake = _client([("GET", "/market-data/search", 200, [])])
        with self.assertRaises(LookupError) as cm:
            t.instrument_id("BTCUSD")
        self.assertIs(type(cm.exception), LookupError)
        self.assertEqual(str(cm.exception),
                         "eToro knows no instrument spelled 'BTCUSD' "
                         "(asked as 'BTC', VENUE_SPELLING)")
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "BTC"}])
        self.assertEqual(t._ids, {})

    def test_the_order_path_refuses_a_lone_spelling_before_any_post(self):
        """FIX 6 on the order path (2026-09-26): market_order resolves the
        spelling on its own client before the POST, so the lone /search
        answer to WHEAT ('WHEAT.FUT' 97, doc §10) raises there and nothing
        is sent, even on a client that never priced it."""
        t, fake = _client([("GET", "/market-data/search", 200,
                            [{"instrumentId": 97,
                              "internalSymbolFull": "WHEAT.FUT"}]),
                           POST_GLDM])
        with mock.patch("time.sleep"):
            with self.assertRaises(LookupError) as cm:
                t.market_order("WHEAT", "BUY", 1, stop_loss=5.0,
                               take_profit=6.0)
        self.assertEqual(cm.exception.lone_id, 97)
        self.assertFalse([c for c in fake.calls if c[0] == "POST"],
                         "an order was POSTed on an unverified spelling")

    def test_a_close_on_btcusd_sends_instrument_100000(self):
        """close_position keys its body on the id instrument_id answers:
        the platform's BTCUSD closes InstrumentID 100000 (BTC, doc §10),
        asked as BTC. UnitsToDeduct is never sent (measured 2026-09-23)."""
        t, fake = _client([SEARCH_BTC,
                           ("POST", "market-close-orders", 200,
                            CLOSE_RESPONSE)])
        out = t.close_position("3603281458", "BTCUSD")
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(post[2]["json"], {"InstrumentID": 100000})
        self.assertEqual(self._searches(fake),
                         [{"internalSymbolFull": "BTC"}])
        self.assertEqual(out["status"], "PENDING")


# ── THE REAL ACCOUNT, MEASURED 2026-09-26 (Saturday ~21:25-22:03 UTC, code
# 097e72c, sent by the operator through a shell client built env='live';
# deploy/ETORO_DEPARTURE.md §4 D5). Every literal below was printed by the
# real adapter on the REAL account unless a docstring says "composed"; the
# fake wire answers the real segment's own spellings — no segment on the
# POST, the lookup, the close and the reads. ────────────────────────────────
REAL_BTC_ACCEPTED = {"token": "<not captured>", "orderId": 1596774178,
                     "referenceId": "<not captured>"}


def _real_btc_lookup(state="open"):
    """orders:lookup (no segment) of order 1596774178 — BTC 0.0002 BUY at
    1x, FILLED at once. Printed: the adapter's FILLED; asset.settlementType
    'REAL' at leverage 1; requestedAmount 16.83, frozenAmount 17.0,
    totalCosts 0.17; openStopLossRate 79934.97 (the SENT stop, kept on
    the top level) and the target 88349.17 kept; positionExecutions[0]:
    positionId 3588477891, stopLossRate 75745.8 (the HELD stop); the
    values avgPrice 84145.8, fees 0.17, marketSpread 0 and markup 0.
    Composed: the wire status {3, Filled} (the sitting printed the
    adapter's FILLED, not the id — 3 is the demo's measured Filled);
    openingData as the PLACE of avgPrice, fees, marketSpread and markup
    (their values were printed, not where they sit on this body — the
    demo body carries them there, D2); openingData.units 0.0002 (the
    units sent — the print named the fill, not its units); and the body
    after the close: this one with state "closed" (the adapter printed
    the word)."""
    return {
        "orderId": 1596774178,
        "status": {"id": 3, "name": "Filled", "errorCode": 0},
        "asset": {"settlementType": "REAL", "leverage": 1},
        "requestedAmount": 16.83, "frozenAmount": 17.0,
        "openStopLossRate": 79934.97, "openTakeProfitRate": 88349.17,
        "totalCosts": 0.17,
        "positionExecutions": [{
            "positionId": 3588477891, "state": state,
            "stopLossRate": 75745.8, "takeProfitRate": 88349.17,
            "openingData": {"units": 0.0002, "avgPrice": 84145.8,
                            "fees": 0.17, "marketSpread": 0,
                            "markup": 0}}],
    }


REAL_BTC_CLOSE = {"orderForClose": {"positionID": 3588477891,
                                    "instrumentID": 100000,
                                    "orderID": 1596736969, "orderType": 19,
                                    "statusID": 1}}
# The cells printed {available_cash 2249.65, used_margin 0.0} alone.
# Composed: accountCurrency "USD" — the account's currency is the one the
# same evening's net_liquidation read printed (2249.98, 'USD'), not a
# field of this print.
REAL_CELLS_AFTER_CLOSE = {"accountCurrency": "USD",
                          "accountTotals": {"accountAvailableCash": 2249.65,
                                            "accountTotalUsedMargin": 0.0}}


class TheRealAccountProofTests(SimpleTestCase):
    """THE PROOFS MEASURED ON THE REAL ACCOUNT (ETORO_PROVEN,
    deploy/ETORO_DEPARTURE.md §7 bullet 0). The rule asks for a demo
    fill-and-close per class; one on the REAL account is the stronger —
    the same adapter, the real segment's own spellings, real settlement —
    and the rule reads "demo or real" since 2026-09-26. The real
    EtoroTrader over a fake wire, as every pin in this file."""

    def test_proof_crypto(self):
        """MEASURED ON THE REAL ACCOUNT, 2026-09-26: BTC 0.0002 BUY at 1x,
        stop 79934.97 / target 88349.17 sent (the last 84142.07 x 0.95 /
        x 1.05). FILLED at once — order 1596774178, position 3588477891,
        avgPrice 84145.8, settlementType REAL, fees 0.17 (1%, one side),
        the stop HELD at 75745.8 (eToro rewrote it: 9.98% under the fill).
        CLOSED at 22:03:24 UTC by the market-close POST with no segment:
        orderForClose{orderID 1596736969, orderType 19, statusID 1}, proven
        by the open order's positionExecutions[0].state "closed"; 5 s
        later available cash 2249.65, used margin 0.0, no position, and
        broker_portfolio empty. Round trip 0.33 USD (2249.98 -> 2249.65).
        "crypto" joins ETORO_PROVEN in the commit that pins this, at 1x
        only (ETORO_PROVEN_LEVERAGE stays empty)."""
        t, fake = _client([
            SEARCH_BTC,
            ("POST", "/api/v2/trading/execution/orders", 200,
             REAL_BTC_ACCEPTED),
            ("POST", "/market-close-orders/positions/3588477891", 200,
             REAL_BTC_CLOSE),
            ("GET", "/api/v1/trading/info/aggregate-portfolio", 200,
             REAL_CELLS_AFTER_CLOSE),
            ("GET", "/api/v1/trading/info/portfolio", 200,
             {"clientPortfolio": {"positions": []}})], env="live")
        _lookup_router(fake, by_order=[(200, _real_btc_lookup("open")),
                                       (200, _real_btc_lookup("closed"))])
        with mock.patch("time.sleep"):
            r = t.market_order("BTC", "BUY", 0.0002, stop_loss=79934.97,
                               take_profit=88349.17)
        # the order that went: the real segment, BTC, 1x, both legs
        post = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(post[1], f"{BASE}/api/v2/trading/execution/orders")
        body = post[2]["json"]
        self.assertEqual((body["symbol"], body["units"], body["leverage"],
                          body["stopLossRate"], body["takeProfitRate"]),
                         ("BTC", 0.0002, 1, 79934.97, 88349.17))
        # the fill, read by orderId on the real lookup
        polls = _polls(fake)
        self.assertEqual(polls[0][1],
                         f"{BASE}/api/v2/trading/info/orders:lookup")
        self.assertEqual(polls[0][2]["params"], {"orderId": "1596774178"})
        self.assertEqual((r["orderId"], r["status"], r["executedQty"],
                          r["avgPrice"], r["positionId"]),
                         ("1596774178", "FILLED", "0.0002", "84145.8",
                          "3588477891"))
        self.assertEqual((r["venueStopLoss"], r["venueTakeProfit"]),
                         (75745.8, 88349.17))
        self.assertTrue(r["protectedOnFill"])
        lk = r["raw"]["lookup"]
        self.assertEqual(lk["asset"], {"settlementType": "REAL",
                                       "leverage": 1})
        self.assertEqual(lk["openStopLossRate"], 79934.97,
                         "the top level keeps the SENT stop")
        self.assertEqual((lk["requestedAmount"], lk["frozenAmount"],
                          lk["totalCosts"]), (16.83, 17.0, 0.17))
        opening = lk["positionExecutions"][0]["openingData"]
        self.assertEqual((opening["fees"], opening["marketSpread"],
                          opening["markup"]), (0.17, 0, 0))
        self.assertAlmostEqual(opening["fees"] / lk["requestedAmount"],
                               0.01, places=3)
        # the close by position id, proven by the OPEN order
        with mock.patch("time.sleep"):
            c = t.close_position("3588477891", "BTC",
                                 open_order_id="1596774178")
        close_post = [x for x in fake.calls if x[0] == "POST"][1]
        self.assertEqual(close_post[1],
                         f"{BASE}/api/v1/trading/execution/"
                         f"market-close-orders/positions/3588477891")
        self.assertEqual(close_post[2]["json"], {"InstrumentID": 100000})
        self.assertEqual((c["status"], c["positionState"], c["orderId"],
                          c["openOrderId"]),
                         ("FILLED", "closed", "1596736969", "1596774178"))
        self.assertEqual(c["raw"]["orderForClose"],
                         REAL_BTC_CLOSE["orderForClose"])
        self.assertNotIn("executedQty", c, "no units asked, none claimed")
        self.assertNotIn("avgPrice", c, "a close carries no price")
        # the cells and the book after
        self.assertEqual(t.margin_cells(), {"available_cash": 2249.65,
                                            "used_margin": 0.0,
                                            "currency": "USD"})
        self.assertEqual(t.get_positions(), [])
        self.assertEqual(t.broker_portfolio(), [])
        for _m, url, _k in fake.calls:
            self.assertNotIn("/demo/", url, url)
            self.assertNotIn("/real/", url, url)
