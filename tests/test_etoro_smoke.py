"""etoro_smoke: four states per read, no order ever, no web lane.

  * It refuses to run without an eToro row or without both keys — and says
    which, without building a client.
  * Each read is reported ok / refused / no-such / unknown: a 401 is eToro's
    own no to the keys; a /search that answered 200 and nothing is eToro's
    own no to a spelling (NO SUCH SPELLING); a lone search result spelled
    differently, a zero quote, a 403 nobody measured and a swallowed
    failure are all 'unknown' and say so — because an adapter bug read as
    "your keys are refused" is the misdiagnosis this command exists to
    prevent, and a zero printed as a price is the one the engine refuses.
  * The stub is the REAL EtoroTrader with its transport replaced — never a
    subclass, because capabilities.adapter_key reads the class name and a
    subclass would answer "" (house rule, tests/test_etoro_client.py).
  * Every wire call it makes is a GET, no write URL is ever hit, the other
    world is not pinged unless asked, the ops page cannot run it, and no
    key reaches the output — not even when the transport quotes one.
"""
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from bot_program.engine import capabilities as cap
from bot_program.engine.etoro_client import BASE, EtoroTrader
from bot_program.models import AssetBotConfig, AssetBotTrade, EtoroAccount

RAW_API, RAW_USER = "api-key-never-printed-7f3a", "user-key-never-printed-9c1d"


class _Resp:
    """Like tests/test_etoro_client._Resp, but raise_for_status raises the
    REAL requests.HTTPError with a response — the smoke's verdict reads the
    status code and the body off it, and a RuntimeError would make every
    refusal 'unknown'."""

    def __init__(self, status, payload=None, url=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url: {self.url}",
                                     response=self)


class _FakeSession:
    """Routes (method, substring of "url?k=v&k=v&") -> (status, payload).
    Records every call. The params are folded into the match string, each
    terminated by "&", so "GLD&" cannot match "GLDM&" and two /search calls
    for two spellings answer differently."""

    def __init__(self, routes=None, default=(200, {})):
        self.routes = list(routes or [])
        self.default = default
        self.calls = []

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        params = kw.get("params") or {}
        probe = (url + "?"
                 + "".join(f"{k}={v}&" for k, v in sorted(params.items())))
        for m, sub, status, payload in self.routes:
            if m == method and sub in probe:
                return _Resp(status, payload, url)
        return _Resp(*self.default, url=url)

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def patch(self, url, **kw):
        return self._hit("PATCH", url, **kw)


class _Quoting:
    """A transport that refuses the header the way requests does — quoting
    the VALUE, which is the key."""

    def __init__(self, key):
        self.key = key
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        raise requests.exceptions.InvalidHeader(
            "Invalid leading whitespace, reserved character(s), or return "
            f"character(s) in header value: {self.key!r}")


REAL = {
    "accountCurrency": "USD",
    "accountTotals": {"accountTotalValue": 1234.56, "accountAvailableCash": 1.4,
                      "accountBalance": 1.4, "accountCurrentPnl": 0,
                      "accountFrozenCash": 0, "accountTotalUsedMargin": 0},
    "cid": 1, "instrumentAggregates": [], "mirrors": [], "timestamp": "t",
}

# the MEASURED candles shape (2026-09-23, real key): one group per
# instrument, the bars one level down
CANDLES = {"candles": [{"instrumentId": 1001, "candles": [
    {"instrumentID": 1001, "fromDate": "2026-09-22T08:00:00Z", "open": 84,
     "high": 85, "low": 83, "close": 84.5, "volume": 10},
    {"instrumentID": 1001, "fromDate": "2026-09-22T09:00:00Z", "open": 84.5,
     "high": 85, "low": 84, "close": 84.7, "volume": 11},
    {"instrumentID": 1001, "fromDate": "2026-09-22T10:00:00Z", "open": 84.7,
     "high": 85, "low": 84, "close": 84.9, "volume": 12},
]}], "interval": "OneHour"}

ROUTES = [
    ("GET", "/info/demo/aggregate-portfolio", 401, {}),
    ("GET", "/info/aggregate-portfolio", 200, REAL),
    ("GET", "/info/portfolio", 200, {"positions": [
        {"positionID": 1, "instrumentID": 1001, "isBuy": True, "units": 2,
         "openRate": 84.8},
        {"positionID": 2, "instrumentID": 4242, "isBuy": False, "units": 3},
    ]}),
    ("GET", "search?internalSymbolFull=GLDM&", 200,
     [{"instrumentId": 1001, "internalSymbolFull": "GLDM"}]),
    ("GET", "search?internalSymbolFull=HYG&", 200,
     [{"instrumentId": 1002, "internalSymbolFull": "HYG"}]),
    ("GET", "search?internalSymbolFull=NOPE&", 200, []),
    ("GET", "search?internalSymbolFull=ZERO&", 200,
     [{"instrumentId": 1003, "internalSymbolFull": "ZERO"}]),
    # a lone result spelled differently: the adapter REFUSES it since
    # 2026-09-26 (FIX 6) and the smoke prints it 'unknown'
    ("GET", "search?internalSymbolFull=SLV&", 200,
     [{"instrumentId": 1004, "internalSymbolFull": "SLVX"}]),
    ("GET", "search?internalSymbolFull=BOOM&", 503, {}),
    ("GET", "rates?instrumentIds=1001&", 200, {"rates": []}),
    ("GET", "rates?instrumentIds=1002&", 200,
     {"rates": [{"bid": 78.5, "ask": 78.7, "lastExecution": 78.6}]}),
    # the second empty-quote shape: a rates row present, every figure 0
    ("GET", "rates?instrumentIds=1003&", 200,
     {"rates": [{"bid": 0, "ask": 0, "lastExecution": 0}]}),
    ("GET", "instruments/1001/history/candles", 200, CANDLES),
    ("GET", "instruments/1002/history/candles", 200, {"candles": []}),
    ("GET", "instruments/1003/history/candles", 200, {"candles": []}),
]


def _keyed(user, *, demo=False, keyed=True, api=RAW_API, user_key=RAW_USER):
    acct = EtoroAccount.objects.create(user=user, demo=demo)
    if keyed:
        acct.set_credentials(api, user_key)
    acct.save()
    return acct


def _live_cfg(user, name, symbols, asset_class="stock", base_currency="EUR"):
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="live",
        enabled=False, symbols=symbols, capital=Decimal("150"),
        base_currency=base_currency)


def _trade(cfg, symbol, *, paper=False, status="OPEN", meta=None):
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side="BUY",
        qty=Decimal("3"), entry_price=Decimal("78.575"), status=status,
        paper=paper, metadata=meta if meta is not None else {})


class SmokeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("et_smoke", password="x")

    def _run(self, routes=ROUTES, default=(200, {}), session=None, **kw):
        """The real class, its transport swapped on the CLASS — no subclass,
        no MagicMock — so both clients the command can build (the row's
        world and the other one) share one recording session."""
        fake = session if session is not None else _FakeSession(routes, default)
        out = StringIO()
        with mock.patch.object(EtoroTrader, "_sess", lambda self: fake):
            call_command("etoro_smoke", user="et_smoke", stdout=out, **kw)
        return out.getvalue(), fake

    def test_no_user_is_a_command_error(self):
        with self.assertRaises(CommandError) as cm:
            call_command("etoro_smoke", user="nobody", stdout=StringIO())
        self.assertIn("no user", str(cm.exception))

    def test_no_row_means_no_client_is_built(self):
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader") as trader:
            with self.assertRaises(CommandError) as cm:
                call_command("etoro_smoke", user="et_smoke", stdout=StringIO())
        self.assertIn("no eToro row", str(cm.exception))
        trader.assert_not_called()

    def test_an_unkeyed_row_refuses_without_touching_etoro(self):
        _keyed(self.user, keyed=False)
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader") as trader:
            with self.assertRaises(CommandError) as cm:
                call_command("etoro_smoke", user="et_smoke", stdout=StringIO())
        self.assertIn("not keyed", str(cm.exception))
        trader.assert_not_called()

    def test_four_states_are_told_apart_and_tallied(self):
        _keyed(self.user)
        cfg = _live_cfg(self.user, "commodity_etf",
                        ["GLDM", "HYG", "NOPE", "ZERO", "SLV"])
        _live_cfg(self.user, "manual", [])
        body, _ = self._run(symbol=["BOOM"], other_world=True)
        tag = f"[{cfg.id}]"
        # the row: never a key, and what an unticked row still IS
        self.assertIn("label 'Main'", body)
        self.assertIn("demo False", body)
        self.assertIn("carries NOTHING", body)
        self.assertIn("still counted by reconcile_asset.keyed_venue_count", body)
        self.assertIn("keyed yes", body)
        # the row's world, and the currency read from the same payload
        self.assertIn("ok       live ping (aggregate-portfolio)", body)
        self.assertIn("accountTotals", body)
        self.assertIn("accountCurrency USD", body)
        self.assertIn("ok       live ping()", body)
        self.assertIn("1,234.56 USD", body)
        # the margin cells the headroom gate reads, off the same payload
        self.assertIn("ok       live margin_cells (accountTotals)", body)
        self.assertIn("available cash 1.40 · used margin 0.00 USD", body)
        # every live config, enabled or not, and the currency it does not share
        self.assertIn("commodity_etf stock enabled=False · 5 symbols", body)
        self.assertIn("base EUR ≠ account USD — the platform converts nothing", body)
        self.assertIn("(no symbols — nothing to resolve)", body)
        # the symbols: an id with eToro's spelling, two empty-quote shapes,
        # eToro's own no, a lone result spelled differently, could-not-ask
        self.assertIn(f"ok       {tag} GLDM", body)
        self.assertIn("instrument 1001 (GLDM) · no rate (lastPrice '0'", body)
        self.assertIn(f"ok       {tag} GLDM klines 1h", body)
        self.assertIn("3 bars on 1h · newest close 84.9", body)
        self.assertIn("instrument 1002 (HYG) · last 78.6 bid 78.5 ask 78.7", body)
        self.assertIn("0 bars on 1h — the venue is mute here", body)
        self.assertIn(f"no-such  {tag} NOPE", body)
        self.assertIn("NO SUCH SPELLING AT ETORO: eToro knows no instrument "
                      "spelled 'NOPE'", body)
        self.assertNotIn(f"{tag} NOPE klines", body)
        # the all-zero row is the platform's single sentinel "0" (ticker,
        # the no-rate guard) — no bid/ask keys ride it
        self.assertIn("instrument 1003 (ZERO) · no rate (lastPrice '0'", body)
        self.assertNotIn("last 0", body)
        self.assertIn(f"unknown  {tag} SLV", body)
        self.assertIn("eToro's lone /search result is spelled 'SLVX', not 'SLV'",
                      body)
        self.assertNotIn(f"{tag} SLV klines", body)
        self.assertIn("unknown  --symbol BOOM", body)
        self.assertIn("HTTP 503 — not a verdict on the keys", body)
        # the book, named where this client resolved the id and only there
        self.assertIn("2 open · BUY 2 GLDM · SELL 3 ETORO:4242 [unnamed here]", body)
        self.assertIn("ok       live broker_portfolio", body)
        self.assertIn("0 platform row(s) OPEN or CLOSE_PENDING", body)
        # the other world, with the same pair — asked for
        self.assertIn("refused  demo ping with the SAME pair", body)
        self.assertIn("HTTP 401 — eToro saw the keys and said no", body)
        # the floors, as MEASURED 2026-09-23 and read by the engine — named,
        # never read here: no call added, the run stays GET-only
        self.assertIn("size floor: none in units — the floor is MONEY, "
                      "MEASURED 2026-09-23: minPositionExposure on the "
                      "eligibility row", body)
        self.assertIn("This command does not POST that read", body)
        self.assertIn("deploy/ETORO_DEPARTURE.md §4 D2c-0", body)
        self.assertNotIn("cannot be asked before an order", body)
        self.assertIn("fractional units: MEASURED 2026-09-23 — "
                      "unitsQuantityType 'fractional'", body)
        self.assertIn("This command does not call the eligibility "
                      "endpoint", body)
        self.assertNotIn("a BELIEF", body)
        # the tally
        # 12 = the margin_cells line joined the ping/net_liquidation trio
        self.assertIn("12 ok · 1 refused by eToro · 1 spelling(s) eToro does "
                      "not know · 2 unknown", body)
        self.assertIn("NOT eToro saying no", body)
        self.assertIn("No order was placed", body)

    def test_no_key_reaches_the_output(self):
        _keyed(self.user)
        body, _ = self._run()
        self.assertNotIn(RAW_API, body)
        self.assertNotIn(RAW_USER, body)

    def test_a_key_quoted_by_the_transport_is_scrubbed(self):
        """requests refuses a header value with leading whitespace or a line
        break by quoting the VALUE in the exception text; the command's
        last-resort branch prints exception text. The key, and its escaped
        repr, must not reach stdout."""
        key = " leading-space-key-3c9e\nsecond-line"
        _keyed(self.user, api=key)
        body, fake = self._run(session=_Quoting(key))
        self.assertTrue(fake.calls)
        self.assertNotIn(key, body)
        self.assertNotIn(repr(key)[1:-1], body)
        self.assertNotIn("leading-space-key-3c9e", body)
        self.assertIn("<x-api-key>", body)
        self.assertIn("unknown  live ping (aggregate-portfolio)", body)

    def test_every_wire_call_is_a_get_and_no_write_url_is_ever_hit(self):
        _keyed(self.user)
        _live_cfg(self.user, "commodity_etf", ["GLDM"])
        _, fake = self._run(other_world=True)
        self.assertTrue(fake.calls)
        self.assertEqual({m for m, _u, _k in fake.calls}, {"GET"})
        for _m, url, _k in fake.calls:
            for forbidden in ("/execution/orders", "orders:lookup",
                              "market-close-orders", "/positions/"):
                self.assertNotIn(forbidden, url, url)

    def test_the_other_world_is_not_pinged_by_default(self):
        """Off by default so one run touches one world — and the skipped
        line carries the measurement of 2026-09-23 (one pair opens both
        worlds), never the "unmeasured" it said before that day."""
        _keyed(self.user)
        body, fake = self._run()
        self.assertIn("skipped  demo ping with the SAME pair", body)
        self.assertIn("--other-world", body)
        self.assertIn("measured 2026-09-23: one pair opens both worlds", body)
        self.assertNotIn("mismatched-world request is unmeasured", body)
        self.assertNotIn("demo ping with the SAME pair (measurement)", body)
        for _m, url, _k in fake.calls:
            self.assertNotIn("/info/demo/", url, url)

    def test_the_write_urls_are_named_with_what_the_tree_records(self):
        """Composed and printed so the operator can GET them by hand; never
        called. The real close path carries the one attestation the adapter
        records (a 405 on GET); beside every write URL the DEMO measurement
        of 2026-09-23, never the old 'documented, never measured'."""
        _keyed(self.user)
        body, _ = self._run()
        self.assertIn(f"{BASE}/api/v2/trading/execution/orders", body)
        self.assertIn(f"{BASE}/api/v2/trading/info/orders:lookup", body)
        self.assertIn(f"{BASE}/api/v1/trading/execution/market-close-orders/"
                      f"positions/<positionId>", body)
        self.assertIn(f"{BASE}/api/v2/trading/positions/<positionId>", body)
        self.assertIn("real v3 spelling not attested", body)
        self.assertIn("GET → 405", body)
        self.assertIn("the POST itself has never been sent", body)
        self.assertNotIn("documented, never measured", body)
        self.assertIn("real segment never sent; measured 2026-09-23 on the "
                      "demo segment", body)
        self.assertIn("200 by ?orderId=<int>, 404 by ?referenceId=", body)
        self.assertIn("status is an object {id, name, errorCode}", body)
        self.assertIn("11/WaitingForMarket", body)
        self.assertNotIn("only 3/Filled seen", body)
        self.assertNotIn("no GET of it is recorded", body)
        self.assertNotIn("/real/", body)

    def test_a_demo_row_measures_the_live_world_with_the_same_pair(self):
        _keyed(self.user, demo=True)
        body, _ = self._run(routes=[
            ("GET", "/info/demo/aggregate-portfolio", 200, REAL),
            ("GET", "/info/aggregate-portfolio", 401, {}),
            ("GET", "/info/demo/portfolio", 200, {"positions": []}),
        ], other_world=True)
        self.assertIn("demo True", body)
        self.assertIn("ok       demo ping (aggregate-portfolio)", body)
        self.assertIn("refused  live ping with the SAME pair", body)
        self.assertIn("0 open — an empty list is an answer", body)
        self.assertIn(f"{BASE}/api/v1/trading/execution/demo/market-close-orders/"
                      f"positions/<positionId>", body)
        # the demo close path was POSTed on 2026-09-23 (never GET-probed):
        # the note carries the measurement and must not say 405
        self.assertIn("measured 2026-09-23 on the demo segment: POST 2xx",
                      body)
        self.assertIn("orderType 19", body)
        self.assertIn("positionExecutions[0].state turning 'closed'", body)
        self.assertIn(f"{BASE}/api/v3/trading/execution/demo/orders/<orderId>",
                      body)
        self.assertIn("202", body)
        self.assertIn("Canceled", body)
        self.assertNotIn("no GET of it is recorded in the tree", body)
        self.assertNotIn("documented, never measured", body)
        self.assertNotIn("GET → 405", body)

    def test_a_swallowed_failure_is_not_ok(self):
        """net_liquidation and broker_portfolio answer None on an exception
        (etoro_client swallows it). A None under a refused key is 'unknown',
        never an 'ok' line saying 'None'."""
        _keyed(self.user)
        body, _ = self._run(routes=[], default=(401, {}))
        self.assertIn("refused  live ping (aggregate-portfolio)", body)
        self.assertIn("unknown  live ping()", body)
        self.assertIn("unknown  live net_liquidation", body)
        self.assertIn("the adapter swallowed the failure", body)
        self.assertIn("refused  live book (get_positions)", body)
        self.assertIn("unknown  live broker_portfolio", body)
        # 4 = ping(), net_liquidation, margin_cells, broker_portfolio
        self.assertIn("0 ok · 2 refused by eToro · 0 spelling(s) eToro does "
                      "not know · 4 unknown", body)

    def test_the_currency_note_is_three_state(self):
        """No accountCurrency in the payload is 'unmeasured', printed —
        never the silence that reads as 'same currency'."""
        _keyed(self.user)
        _live_cfg(self.user, "manual", [])
        no_ccy = {k: v for k, v in REAL.items() if k != "accountCurrency"}
        body, _ = self._run(routes=[
            ("GET", "/info/aggregate-portfolio", 200, no_ccy),
            ("GET", "/info/portfolio", 200, {"positions": []}),
        ])
        self.assertIn("accountCurrency ABSENT", body)
        self.assertIn("account currency unmeasured (no accountCurrency read "
                      "from aggregate-portfolio) — the platform converts "
                      "nothing", body)
        self.assertNotIn("≠", body)

    def test_an_unstamped_platform_row_is_named_outside_this_book(self):
        """Three OPEN live rows on the VPS carry no broker stamp; an empty
        eToro book must not read as their absence. Counted in Python — the
        ORM's exclude(metadata__broker=...) drops a row whose metadata never
        had the key."""
        _keyed(self.user)
        cfg = _live_cfg(self.user, "manual", [])
        _trade(cfg, "HYG", meta={"protective_trade_id": "64"})   # unstamped
        _trade(cfg, "NEM", meta={"broker": "etoro"})             # stamped here
        _trade(cfg, "GLDM", meta={"broker": "ibkr"})             # stamped elsewhere
        _trade(cfg, "AAPL", paper=True)                          # paper: not live
        _trade(cfg, "MSFT", status="CLOSED")                     # closed: not open
        body, _ = self._run(routes=[
            ("GET", "/info/aggregate-portfolio", 200, REAL),
            ("GET", "/info/portfolio", 200, {"positions": []}),
        ])
        self.assertIn("0 open — an empty list is an answer", body)
        self.assertIn("2 platform row(s) OPEN or CLOSE_PENDING, live, not "
                      "stamped broker=etoro — this book says nothing about "
                      "them (reconcile_asset.unattributable)", body)

    def test_the_stub_is_the_real_class(self):
        """The house rule in one assertion: with the transport patched the
        instance still answers 'etoro' to adapter_key, which a subclass or a
        MagicMock would not."""
        fake = _FakeSession(ROUTES)
        with mock.patch.object(EtoroTrader, "_sess", lambda self: fake):
            t = EtoroTrader("k", "u", env="live")
            self.assertEqual(cap.adapter_key(t), "etoro")
            self.assertFalse(cap.has_capability(t, "size_floor"))
            self.assertTrue(cap.has_capability(t, "account"))

    def test_it_is_registered_but_never_web_runnable(self):
        from core import ops_commands
        entry = ops_commands.get("etoro_smoke")
        self.assertIsNotNone(entry)
        self.assertTrue(entry["read_only"])
        self.assertFalse(ops_commands.is_runnable(entry))
        self.assertNotIn("etoro_smoke", ops_commands.runnable_names())

    def test_nothing_in_the_command_can_place_an_order(self):
        from pathlib import Path

        from bot_program.management.commands import etoro_smoke
        src = Path(etoro_smoke.__file__).read_text(encoding="utf-8")
        for word in ("market_order", "close_position", "modify_protective",
                     "modify_target", "_patch_position", "_await_fill",
                     ".post(", ".patch(", ".delete(", "cancel_order",
                     "order_status"):
            self.assertNotIn(word, src, word)

    def test_a_mapped_spelling_prints_both_and_every_symbol_its_route(self):
        """E3.6 (2026-09-26). The platform's BTCUSD is asked as BTC
        (VENUE_SPELLING: /search answered BTC 100000 and nothing for BTCUSD
        on 2026-09-23) and prints "(BTC ← BTCUSD)"; the book names the
        position BTCUSD. Every config symbol carries its route —
        broker_name_for_symbol, the same default client_for_symbol routes
        on: a symbol with no Instrument row routes as crypto, and an index
        in a stock config says so. The run stays GET-only."""
        from instruments.models import Instrument
        acct = _keyed(self.user)
        acct.is_primary_for_crypto = True
        acct.save()
        for sym, cls in (("BTCUSD", "crypto"), ("SPX500", "index")):
            Instrument.objects.get_or_create(
                symbol=sym, defaults={"name": sym, "asset_class": cls})
        _live_cfg(self.user, "crypto", ["BTCUSD", "NOROW"],
                  asset_class="crypto")
        _live_cfg(self.user, "megacaps", ["SPX500"])
        body, fake = self._run(routes=[
            ("GET", "/info/aggregate-portfolio", 200, REAL),
            ("GET", "/info/portfolio", 200, {"positions": [
                {"positionID": 9, "instrumentID": 100000, "isBuy": True,
                 "units": 1}]}),
            ("GET", "search?internalSymbolFull=BTC&", 200,
             [{"instrumentId": 100000, "internalSymbolFull": "BTC"}]),
            ("GET", "search?internalSymbolFull=SPX500&", 200,
             [{"instrumentId": 27, "internalSymbolFull": "SPX500"}]),
            ("GET", "search?internalSymbolFull=NOROW&", 200, []),
            # the measured quote (doc §10: BTC 85,710.6 / 85,720.46, 24/7)
            ("GET", "rates?instrumentIds=100000&", 200,
             {"rates": [{"bid": 85710.6, "ask": 85720.46}]}),
            ("GET", "rates?instrumentIds=27&", 200, {"rates": []}),
            ("GET", "instruments/100000/history/candles", 200,
             {"candles": []}),
        ])
        self.assertIn("instrument 100000 (BTC ← BTCUSD) · last", body)
        self.assertIn("bid 85710.6 ask 85720.46", body)
        self.assertIn("instrument 27 (SPX500) · no rate", body)
        self.assertNotIn("(SPX500 ←", body)
        self.assertIn("route=etoro · eToro spells it BTC", body)
        self.assertIn("route=etoro · [no Instrument row → routes as crypto, "
                      "no bars]", body)
        self.assertIn("route=alpaca · [index in a stock config]", body)
        self.assertIn("no-such  [", body)
        self.assertIn("1 open · BUY 1 BTCUSD", body)
        self.assertNotIn("ETORO:100000", body)
        self.assertEqual({m for m, _u, _k in fake.calls}, {"GET"})
        searched = [k.get("params") for _m, u, k in fake.calls
                    if "/search" in u]
        self.assertIn({"internalSymbolFull": "BTC"}, searched)
        self.assertNotIn({"internalSymbolFull": "BTCUSD"}, searched)

    def test_a_route_that_cannot_be_named_is_named_by_type(self):
        """_route_note reads the route from the database only; when that
        read raises, the line names the failure by type, "route=?
        (RuntimeError: ...)", and the smoke goes on, still GET-only."""
        _keyed(self.user)
        _live_cfg(self.user, "commodity_etf", ["GLDM", "HYG"])
        with mock.patch(
                "bot_program.engine.broker_router.broker_name_for_symbol",
                side_effect=RuntimeError("router unreadable")):
            body, fake = self._run()
        self.assertEqual(
            body.count("route=? (RuntimeError: router unreadable)"), 2)
        self.assertIn("instrument 1002 (HYG) · last 78.6 bid 78.5 ask 78.7",
                      body)
        self.assertEqual({m for m, _u, _k in fake.calls}, {"GET"})

