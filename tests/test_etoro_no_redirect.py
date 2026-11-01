"""NO eToro REQUEST FOLLOWS A REDIRECT (2026-11-01).

The real-money eToro client (bot_program/engine/etoro_client.py) sent every
request through a plain requests.Session, and requests follows a redirect by
default, from inside Session.send, where no check of the client sees it: a
301, 302 or 303 as a GET, a 307 or a 308 with the same method and body.
requests drops Authorization when a redirect changes host and keeps every
other header. eToro's keys ARE other headers: the session carries x-api-key
and x-user-key on every request (EtoroTrader._sess), beside the x-request-id
of each call. So one redirect to another host handed both keys to that host,
and an order POST answered 307 was sent again there. The demo proof client
alone refused redirects (2026-10-31, its wire).

Now every eToro request refuses a redirect, on both worlds and for every
method, through one place, the session the client builds
(etoro_client.NoRedirectSession), and the requests.* call that reaches
eToro outside the client passes allow_redirects=False
(dashboard/views_brokers.etoro_probe); the legacy market-data adapter
(market_data/adapters/etoro_adapter.EtoroClient) stands on the client's
session:

  * a 3xx is never followed and nothing is sent after it; it is a failure,
    logged with its status and the host it points at, nothing more (no
    path, no query string, never a header);
  * a READ answered so is a failed read, noted on the venue's health with
    its code as a 5xx is (a background read notes nothing, as it notes no
    5xx), and never asked again;
  * a WRITE answered so is IN DOUBT, never "not sent": the order POST
    raises EtoroOrderInDoubt (the engine notes the symbol and sends nothing
    again), the close answers inDoubt (the bot lane, the drain and the
    kill switch hold it, whichever lane wrote the marker, and send no
    second close until the venue's own word or a book read past its lag
    settles it), the stop or target PATCH answers inDoubt, the DELETE
    answers None (not proven); each is noted on the venue's health as a
    write;
  * the demo proof client keeps its own refusal, on top;
  * a source pin fails on a new request site of an eToro module (one that
    composes an eToro URL, imports the client in any form, names one of
    its classes or holds one of its key headers) that may follow a
    redirect: a requests session, Session subclass, urllib opener,
    aiohttp session, urllib3 pool or websockets connection of its own, a
    requests or aiohttp verb without allow_redirects=False, urllib3.request
    without redirect=False, or follow_redirects that is not False (httpx);
    and (the S3 review's second pass) the same in curl_cffi,
    websocket-client, aiohttp_retry and Twisted's redirect agents,
    requests reached through another module or bound twice in one, a
    following callable handed on or stored where it is not called
    (partial, to_thread, submit, getattr, an alias, a default_factory),
    and a star import or an import at run time that hides what it binds.

Every test mounts a fake eToro UNDER a real requests.Session (_Venue), so
what requests itself would do with a redirect is what is measured: the other
host answers too, and records whatever reached it.

Run with:  python manage.py test tests.test_etoro_no_redirect
"""
import ast
import json
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from requests.adapters import BaseAdapter
from requests.models import Response

from bot_program import venue_health as vh
from bot_program.engine.etoro_client import (BASE, EtoroOrderInDoubt,
                                             EtoroTrader, RedirectRefused)
from tests.test_etoro_client import (ELIG_AAPL, ELIG_AAPL_LIVE, SEARCH_AAPL,
                                     _FakeSession, _clear_eligibility,
                                     _held_lookup, _lookup, _lookup_router)

LOGGER = "bot_program.engine.etoro_client"
#: eToro's own host and domain, read off the client, never written here.
ETORO = urlsplit(BASE).netloc
ETORO_DOMAIN = ".".join(urlsplit(BASE).hostname.split(".")[-2:])
#: Where a redirect points: a reserved name nothing answers for real.
OTHER_HOST = "other-host.invalid"
OTHER = f"https://{OTHER_HOST}"
#: A Location whose path and query must never reach a log line.
ELSEWHERE = OTHER + "/elsewhere/path?token=abc"
RATES = ("GET", "/instruments/rates", 200, {"rates": [
    {"bid": 99.9, "ask": 100.1, "lastExecution": 100.0}]})
ORDERS = "/execution/demo/orders"
CLOSE = "/market-close-orders/positions/900001"
CLOSE_OWN = "/market-close-orders/positions/900002"
ROUTER = "bot_program.engine.broker_router.client_for_symbol"
PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"
STAFF = "bot_program.notifications.notify_staff"
KILL = "bot_program.engine.kill_switch"
PORTFOLIO = "/info/demo/portfolio"
#: The demo book listing the row's position (900001, instrument 1001, which
#: the search names AAPL, ten units long), and the same book without it.
LISTED = ("GET", PORTFOLIO, 200, {"clientPortfolio": {"positions": [{
    "positionID": 900001, "instrumentID": 1001, "isBuy": True,
    "units": 10.0, "orderID": 1000001}]}})
UNLISTED = ("GET", PORTFOLIO, 200, {"clientPortfolio": {"positions": []}})


def _proof(state):
    """orders:lookup of the row's OPEN order with its position `state`
    ("open" or "closed"): the venue's own word, read by position_state."""
    body = _lookup(3)
    body["positionExecutions"][0]["state"] = state
    return body


class _Venue(BaseAdapter):
    """eToro and every other host, under a REAL requests.Session. A request
    to eToro whose (method, path suffix) is in `redirects` is answered with
    that 3xx and its Location (none when ""); every other request to eToro
    is answered by `wire` (tests.test_etoro_client._FakeSession routes, the
    client's paths as the other suites write them); a request to any other
    host is answered 200 {}. So a redirect requests followed shows here as
    a second request, with the headers it carried. Nothing leaves the box."""

    def __init__(self, routes=(), redirects=None, *, host=ETORO):
        super().__init__()
        self.wire = _FakeSession(list(routes))
        self.redirects = dict(redirects or {})
        self.host = host
        self.sent = []

    def send(self, request, **kw):
        parts = urlsplit(request.url)
        self.sent.append((request.method, request.url, dict(request.headers)))
        r = Response()
        r.request, r.url = request, request.url
        r.headers["Content-Type"] = "application/json"
        r._content_consumed = True
        if parts.netloc != self.host:
            r.status_code, r._content = 200, b"{}"
            return r
        for (method, suffix), (code, location) in self.redirects.items():
            if request.method == method and parts.path.endswith(suffix):
                r.status_code, r._content = code, b""
                if location:
                    r.headers["Location"] = location
                return r
        got = self.wire._hit(
            request.method, urlunsplit(parts._replace(query="")),
            params=dict(parse_qsl(parts.query)),
            json=json.loads(request.body) if request.body else None)
        r.status_code = got.status_code
        r._content = json.dumps(got._payload).encode()
        return r

    def close(self):
        pass

    def at_other_hosts(self):
        return [s for s in self.sent if urlsplit(s[1]).netloc != self.host]

    def to(self, method, suffix):
        return [s for s in self.sent
                if s[0] == method and urlsplit(s[1]).path.endswith(suffix)]


def _client(venue, env="demo"):
    """The REAL client on the session it builds itself, `venue` under it."""
    t = EtoroTrader("api-k", "user-k", env=env)
    t._sess().mount("https://", venue)
    return t


def _failures(world="demo"):
    return vh._load(vh._key("etoro", world)).get("failures") or []


class _Clean:
    def setUp(self):
        super().setUp()
        vh.reset()
        self.addCleanup(vh.reset)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)


# ── the session: one place, every method, both worlds ────────────────────

class TheSessionRefusesTests(_Clean, SimpleTestCase):

    def test_a_302_to_another_host_on_a_get_sends_one_request_and_no_key(self):
        """The premise first, on requests itself (the control: the venue
        does see a followed redirect, the keys on it, Authorization not);
        then the client: one request, nothing at the other host, never
        asked again, and the log line says the status and the host only."""
        control = _Venue(redirects={("GET", "/market-data/search"):
                                    (302, ELSEWHERE)})
        plain = requests.Session()
        plain.headers.update({"x-api-key": "api-k", "x-user-key": "user-k",
                              "Authorization": "Bearer t"})
        plain.mount("https://", control)
        plain.get(BASE + "/api/v1/market-data/search", timeout=5)
        [(_m, _u, carried)] = control.at_other_hosts()
        self.assertEqual((carried.get("x-api-key"), carried.get("x-user-key")),
                         ("api-k", "user-k"))
        self.assertNotIn("Authorization", carried)

        venue = _Venue([SEARCH_AAPL], redirects={
            ("GET", "/instruments/rates"): (302, ELSEWHERE)})
        t = _client(venue)
        with mock.patch("time.sleep") as sleep, \
                self.assertRaises(RedirectRefused) as cm, \
                self.assertLogs(LOGGER, level="ERROR") as logs:
            t.ticker("AAPL")
        e = cm.exception
        self.assertEqual((e.method, e.status, e.host),
                         ("GET", 302, OTHER_HOST))
        self.assertEqual(len(venue.to("GET", "/instruments/rates")), 1,
                         "the read was asked again")
        self.assertEqual(venue.at_other_hosts(), [],
                         "the redirect was followed")
        sleep.assert_not_called()
        said = "\n".join(logs.output)
        self.assertIn("302", said)
        self.assertIn(OTHER_HOST, said)
        for never in ("elsewhere", "token", "abc", "api-k", "user-k"):
            self.assertNotIn(never, said)

    def test_a_302_to_another_host_on_the_order_post_sends_one_request_and_no_key(self):
        """A 302 (and a 301, a 303: requests resends those as a GET) or a
        307, a 308 (the same POST, body and keys, again): one order POST,
        no lookup, nothing at the other host, and the order is IN DOUBT."""
        for code in (302, 307, 308, 301, 303):
            with self.subTest(code=code):
                vh.reset()
                venue = _Venue([SEARCH_AAPL], redirects={
                    ("POST", ORDERS): (code, ELSEWHERE)})
                t = _client(venue)
                coid = str(uuid.uuid4())
                with mock.patch("time.sleep"), mock.patch(STAFF), \
                        self.assertLogs(LOGGER, level="ERROR"), \
                        self.assertRaises(EtoroOrderInDoubt) as cm:
                    t.market_order("AAPL", "BUY", 1.0, stop_loss=180.0,
                                   take_profit=210.0, client_order_id=coid)
                e = cm.exception
                self.assertTrue(getattr(e, "in_doubt", False))
                self.assertEqual(e.answered, code)
                self.assertEqual(e.reference, coid)
                self.assertEqual((e.redirect.status, e.redirect.host),
                                 (code, OTHER_HOST))
                self.assertTrue(str(e).startswith(
                    f"AAPL: the order was answered HTTP {code}, a redirect"),
                    str(e))
                self.assertIn("not followed", str(e))
                self.assertIn("Do not resend it", str(e))
                self.assertNotIn("elsewhere", str(e))
                self.assertEqual([(m, u) for m, u, _h
                                  in venue.to("POST", ORDERS)],
                                 [("POST", t._v2_exec_orders())])
                self.assertEqual([s for s in venue.sent
                                  if "orders:lookup" in s[1]], [],
                                 "nothing polled: there is no orderId")
                self.assertEqual(venue.at_other_hosts(), [])

    def test_every_method_refuses_every_3xx_on_both_worlds(self):
        """GET, POST, PATCH, DELETE, PUT; every 3xx, a Location or none;
        allow_redirects=True from a caller changes nothing."""
        for env in ("demo", "live"):
            for method in ("GET", "POST", "PATCH", "DELETE", "PUT"):
                for code in (300, 301, 302, 303, 304, 305, 307, 308):
                    with self.subTest(env=env, method=method, code=code):
                        venue = _Venue(redirects={
                            (method, "/api/v1/x"): (code, OTHER + "/y")})
                        s = EtoroTrader("api-k", "user-k", env=env)._sess()
                        s.mount("https://", venue)
                        with self.assertRaises(RedirectRefused) as cm, \
                                self.assertLogs(LOGGER, level="ERROR"):
                            s.request(method, BASE + "/api/v1/x", json={},
                                      allow_redirects=True, timeout=5)
                        self.assertEqual(cm.exception.status, code)
                        self.assertEqual(len(venue.sent), 1, venue.sent)
                        self.assertEqual(venue.at_other_hosts(), [])

    def test_the_client_builds_the_refusing_session_on_both_worlds(self):
        from bot_program.engine.etoro_client import NoRedirectSession
        for env in ("demo", "live"):
            with self.subTest(env=env):
                s = EtoroTrader("api-k", "user-k", env=env)._sess()
                self.assertIsInstance(s, NoRedirectSession)
                self.assertEqual(s.max_redirects, 0)
                self.assertEqual((s.headers["x-api-key"],
                                  s.headers["x-user-key"]),
                                 ("api-k", "user-k"))
                resp = Response()
                resp.status_code = 307
                resp.headers["Location"] = OTHER + "/y"
                self.assertIsNone(s.get_redirect_target(resp),
                                  "a redirect target is never computed")

    def test_the_refusal_says_the_status_and_the_host_and_nothing_more(self):
        for location, host in (
                (ELSEWHERE + "#frag", OTHER_HOST),
                (f"https://usr:pw@{OTHER_HOST}:8443/elsewhere?token=abc",
                 OTHER_HOST),
                ("/elsewhere/path?token=abc", urlsplit(BASE).hostname),
                ("", "")):
            with self.subTest(location=location):
                venue = _Venue(redirects={("GET", "/api/v1/x"):
                                          (302, location)})
                s = EtoroTrader("api-k", "user-k")._sess()
                s.mount("https://", venue)
                with self.assertRaises(RedirectRefused) as cm, \
                        self.assertLogs(LOGGER, level="ERROR") as logs:
                    s.get(BASE + "/api/v1/x?mine=1", timeout=5)
                e = cm.exception
                self.assertEqual(e.host, host)
                said = "\n".join(logs.output) + "\n" + str(e)
                self.assertIn("302", said)
                self.assertIn(host or "no named host", said)
                for never in ("elsewhere", "token", "abc", "frag", "usr",
                              "pw@", "8443", "mine=1", "api-k", "user-k"):
                    self.assertNotIn(never, said)

    def test_a_refused_write_is_in_doubt_by_default_and_a_read_is_not(self):
        """The safe default for a write site nobody classified: the engine
        reads `in_doubt` duck-typed (asset_engine/base.py), so a refused
        POST, PATCH, PUT or DELETE is never read as "not sent"."""
        for method, doubt in (("GET", False), ("HEAD", False),
                              ("POST", True), ("PATCH", True), ("PUT", True),
                              ("DELETE", True)):
            with self.subTest(method=method):
                e = RedirectRefused(method, 302, OTHER_HOST)
                self.assertIs(e.in_doubt, doubt)
                self.assertEqual((e.status, e.host), (302, OTHER_HOST))


# ── a read answered with a redirect: a failed read ──────────────────────

class TheReadsTests(_Clean, SimpleTestCase):

    READS = (
        ("search", "GET", "/market-data/search",
         lambda t: t.instrument_id("AAPL")),
        ("ticker", "GET", "/instruments/rates", lambda t: t.ticker("AAPL")),
        ("account", "GET", "/info/demo/aggregate-portfolio",
         lambda t: t.account()),
        ("portfolio", "GET", "/info/demo/portfolio",
         lambda t: t.get_positions()),
        ("eligibility", "POST", "/info/demo/eligibility",
         lambda t: t.eligibility("AAPL")),
    )

    def test_a_redirected_read_is_a_failed_read_on_the_venues_health(self):
        """Noted with its code at the read's own site, as a 5xx is, after
        ONE request: no read retry, nothing at the other host."""
        from bot_program.engine import etoro_client as ec
        for where, method, path, call in self.READS:
            with self.subTest(where=where):
                vh.reset()
                _clear_eligibility()
                venue = _Venue([SEARCH_AAPL], redirects={
                    (method, path): (302, OTHER + path)})
                t = _client(venue)
                with mock.patch("time.sleep") as sleep, \
                        self.assertRaises(RedirectRefused), \
                        self.assertLogs(LOGGER, level="ERROR"):
                    call(t)
                self.assertEqual(len(venue.to(method, path)), 1)
                self.assertEqual(venue.at_other_hosts(), [])
                sleep.assert_not_called()
                [failure] = _failures()
                self.assertEqual((failure["where"], failure["code"]),
                                 (where, 302))
                self.assertIn(OTHER_HOST, failure["detail"])
                self.assertNotIn(path, failure["detail"])
                self.assertIsNone(vh.sick("etoro", "demo"),
                                  "one failed read makes nothing sick")
        self.assertEqual(ec._ELIGIBILITY, {}, "a redirect cached a row")

    def test_three_redirected_reads_sicken_the_venue_as_three_5xx_do(self):
        venue = _Venue([SEARCH_AAPL], redirects={
            ("GET", "/instruments/rates"): (302, OTHER + "/r")})
        t = _client(venue)
        with mock.patch("time.sleep"), mock.patch(STAFF), \
                self.assertLogs(LOGGER, level="ERROR"):
            for _ in range(3):
                with self.assertRaises(RedirectRefused):
                    t.ticker("AAPL")
        self.assertIsNotNone(vh.sick("etoro", "demo"))
        self.assertEqual(len(venue.to("GET", "/instruments/rates")), 3)

    def test_a_background_read_notes_nothing_as_it_notes_no_5xx(self):
        """The bar refresh's candles (klines, a BACKGROUND read since PR50)
        note no failure on the venue's health; a redirect there neither."""
        venue = _Venue([SEARCH_AAPL], redirects={
            ("GET", "/history/candles/asc/FourHours/5"): (302, OTHER + "/c")})
        t = _client(venue)
        with self.assertRaises(RedirectRefused), \
                self.assertLogs(LOGGER, level="INFO") as logs:
            t.klines("AAPL", "4h", 5)
        self.assertEqual(_failures(), [])
        self.assertTrue(any("background read" in m for m in logs.output))
        self.assertEqual(venue.at_other_hosts(), [])

    def test_the_lookup_and_the_ping_are_failed_reads_too(self):
        """orders:lookup answers could-not-ask (None) and ping False, each
        noted with its code; the lookup's own 5xx stay unnoted (the close's
        measured transient 500s, tests/test_venue_health.py)."""
        venue = _Venue(redirects={
            ("GET", "/info/demo/orders:lookup"): (302, OTHER + "/l"),
            ("GET", "/info/demo/aggregate-portfolio"): (302, OTHER + "/a")})
        t = _client(venue)
        with self.assertLogs(LOGGER, level="ERROR"):
            self.assertIsNone(t.order_status("1000001"))
            self.assertFalse(t.ping())
        self.assertEqual([(f["where"], f["code"]) for f in _failures()],
                         [("lookup", 302), ("ping", 302)])
        self.assertEqual(len(venue.sent), 2)
        self.assertEqual(venue.at_other_hosts(), [])

    def test_the_account_snapshot_is_a_failed_read_and_answers_none(self):
        """account_snapshot (2026-10-31): the sync's ONE aggregate-portfolio
        GET for the equity, the cash cells and the figures, and the read
        asked again after an order (bot_program.etoro_cells). It reads
        through account(), on the client's own session (2026-11-01): a
        redirect answers None after ONE request, noted at the read's own
        site, and nothing reaches the other host."""
        path = "/info/demo/aggregate-portfolio"
        venue = _Venue(redirects={("GET", path): (302, OTHER + path)})
        t = _client(venue)
        with mock.patch("time.sleep") as sleep, \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertIsNone(t.account_snapshot())
        self.assertEqual(len(venue.to("GET", path)), 1)
        self.assertEqual(venue.at_other_hosts(), [])
        sleep.assert_not_called()
        self.assertEqual([(f["where"], f["code"]) for f in _failures()],
                         [("account", 302)])


# ── a write answered with a redirect: in doubt ──────────────────────────

class TheWritesTests(_Clean, SimpleTestCase):

    def test_a_redirected_order_is_noted_on_the_venues_health_as_a_write(self):
        venue = _Venue([SEARCH_AAPL], redirects={("POST", ORDERS):
                                                 (302, OTHER + "/o")})
        t = _client(venue)
        with mock.patch("time.sleep"), mock.patch(STAFF), \
                self.assertRaises(EtoroOrderInDoubt), \
                self.assertLogs(LOGGER, level="ERROR") as logs:
            t.market_order("AAPL", "BUY", 1.0, stop_loss=180.0,
                           take_profit=210.0)
        s = vh.sick("etoro", "demo")
        self.assertIsNotNone(s, "one write failure makes the venue sick")
        self.assertEqual((s["failures"][-1]["where"],
                          s["failures"][-1]["code"]), ("order", 302))
        self.assertIn("in doubt", s["failures"][-1]["detail"])
        self.assertTrue(any("IN DOUBT" in m and "NOT retried" in m
                            for m in logs.output))

    def test_a_redirected_close_is_in_doubt_and_asks_nothing_after_it(self):
        """The answer the drain and the bot lane already read as a close
        that may be live (SaxoTrader's 202 shape): UNKNOWN, inDoubt, nothing
        filled, the reference the close was sent with. No proof is polled
        after it, even with the open order's id in hand."""
        from bot_program.pending_closes import (broker_filled_qty,
                                                order_in_doubt)
        venue = _Venue([SEARCH_AAPL], redirects={("POST", CLOSE):
                                                 (302, OTHER + "/c")})
        t = _client(venue)
        with mock.patch("time.sleep") as sleep, mock.patch(STAFF), \
                self.assertLogs(LOGGER, level="ERROR"):
            out = t.close_position("900001", "AAPL", 10.0,
                                   open_order_id="1000001")
        [(_m, _u, sent)] = venue.to("POST", CLOSE)
        self.assertEqual(out["status"], "UNKNOWN")
        self.assertIs(out["inDoubt"], True)
        self.assertEqual(out["executedQty"], "0.0")
        self.assertEqual(out["positionId"], "900001")
        self.assertEqual(out["reference"], sent["x-request-id"])
        self.assertEqual(out["redirect"], {"status": 302, "host": OTHER_HOST})
        self.assertNotIn("positionState", out)
        self.assertEqual([s for s in venue.sent if "orders:lookup" in s[1]],
                         [], "a proof was polled after the redirect")
        sleep.assert_not_called()
        self.assertEqual(venue.at_other_hosts(), [])
        self.assertTrue(order_in_doubt(out))
        self.assertEqual(broker_filled_qty(out), Decimal(0))
        s = vh.sick("etoro", "demo")
        self.assertIsNotNone(s)
        self.assertIn("close in doubt", s["failures"][-1]["detail"])

    def test_a_redirected_stop_or_target_move_is_in_doubt_never_refused(self):
        for mover in ("modify_protective", "modify_target"):
            with self.subTest(mover=mover):
                vh.reset()
                venue = _Venue(redirects={("PATCH", "/positions/900001"):
                                          (307, OTHER + "/p")})
                t = _client(venue)
                with mock.patch(STAFF), \
                        self.assertLogs(LOGGER, level="ERROR"):
                    res = getattr(t, mover)("900001", 185.0)
                self.assertIs(res["ok"], False)
                self.assertIs(res["inDoubt"], True)
                self.assertIsNone(res["price"])
                self.assertNotIn("refused", res["reason"])
                self.assertIn("redirect", res["reason"])
                self.assertIn("not followed", res["reason"])
                self.assertIn(OTHER_HOST, res["reason"])
                self.assertEqual(len(venue.to("PATCH", "/positions/900001")),
                                 1)
                self.assertEqual(venue.at_other_hosts(), [])
                self.assertIsNotNone(vh.sick("etoro", "demo"))

    def test_a_redirected_delete_is_not_proven_and_reads_nothing_after_it(self):
        """cancel_order reads first (the lookup sees a held order), sends
        the DELETE, meets the redirect: None, not proven, and no lookup is
        asked after it."""
        venue = _Venue(redirects={("DELETE", "/execution/demo/orders/1000001"):
                                  (302, OTHER + "/d")})
        _lookup_router(venue.wire, by_order=(200, _held_lookup()))
        t = _client(venue)
        with mock.patch("time.sleep") as sleep, mock.patch(STAFF), \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertIsNone(t.cancel_order("1000001"))
        self.assertEqual(len(venue.to("DELETE", "/orders/1000001")), 1)
        self.assertEqual(len([s for s in venue.sent
                              if "orders:lookup" in s[1]]), 1,
                         "the lookup is read first and never after")
        sleep.assert_not_called()
        self.assertEqual(venue.at_other_hosts(), [])
        self.assertIn("cancel in doubt",
                      vh.sick("etoro", "demo")["failures"][-1]["detail"])


# ── the engine holds it: nothing is sent again blind ────────────────────

class TheEngineHoldsTests(_Clean, TestCase):

    def setUp(self):
        super().setUp()
        p = mock.patch(STAFF, return_value={"n_delivered": 1})
        self.staff = p.start()
        self.addCleanup(p.stop)

    def _told(self, words):
        return any(words in str(c) for c in self.staff.call_args_list)

    def test_a_redirected_entry_is_noted_in_doubt_and_never_sent_again(self):
        """The bot lane: execute_entry on a LIVE stock config carried by the
        REAL client (tests/test_etoro_leverage.py's fixture). The order
        POST meets a 302: ORDER_IN_DOUBT, the symbol noted, the staff told,
        no row; the next proposal is refused on the note and no second
        order leaves."""
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        from tests.test_desk_seam import _client as _mock_client
        from tests.test_etoro_leverage import _account, _book
        from tests.test_execution_trust import (_cfg, _instrument, _signal,
                                                _user)
        user = _user("s3_entry")
        cfg = _cfg(user, name="NOREDIRECT")
        cfg.base_currency = "USD"
        cfg.save(update_fields=["base_currency"])
        _signal(_instrument(), rule="s3_rule")
        _book(user)
        _account(user, cash=100000)
        bot = StockBot(cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        venue = _Venue([SEARCH_AAPL, RATES, ELIG_AAPL, ELIG_AAPL_LIVE],
                       redirects={("POST", ORDERS): (302, OTHER + "/o")})
        t = _client(venue)
        with mock.patch(ROUTER, return_value=t), \
                mock.patch(PROVEN, frozenset({"stock"})), \
                mock.patch("time.sleep"), \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertIsNone(bot.execute_entry(cand))
        [(_m, _u, sent)] = venue.to("POST", ORDERS)
        self.assertEqual(venue.at_other_hosts(), [])
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(cfg)["AAPL"]["code"],
                         skips.ORDER_IN_DOUBT)
        self.assertEqual(cfg.extras["entry_in_doubt"]["AAPL"]["reference"],
                         sent["x-request-id"])
        self.assertTrue(self._told("may be live"))
        # the next tick: refused on the note, nothing sent
        bot = StockBot(cfg)
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNone(bot.propose_entry("AAPL"))
        cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(cfg)["AAPL"]["code"],
                         skips.ORDER_IN_DOUBT)
        self.assertEqual(len(venue.to("POST", ORDERS)), 1)

    def _row(self, status="OPEN"):
        from bot_program.models import AssetBotTrade
        from tests.test_order_lifecycle import _bot, _open_trade
        user = User.objects.create_user(f"s3_{status.lower()}", password="x")
        bot, cfg = _bot(user)
        trade = _open_trade(cfg, protective_trade_id="900001",
                            broker="etoro", broker_env="paper",
                            initial_stop_loss=190.0)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            status=status, opened_at=timezone.now() - timedelta(days=1))
        trade.refresh_from_db()
        return bot, trade

    def test_a_redirected_close_from_the_bot_lane_is_held_in_doubt(self):
        """AssetBot._close_trade reads the inDoubt answer as a close that
        may be live: the row stays OPEN with close_in_doubt and the close's
        reference, the staff are told, and nothing is sent again."""
        bot, trade = self._row()
        venue = _Venue([SEARCH_AAPL, RATES], redirects={
            ("POST", CLOSE): (302, OTHER + "/c")})
        t = _client(venue)
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="ERROR") as logs, \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertFalse(bot._close_trade(trade, Decimal("205"), t,
                                              reason="TIME"))
        [(_m, _u, sent)] = venue.to("POST", CLOSE)
        self.assertEqual(venue.at_other_hosts(), [])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"],
                         sent["x-request-id"])
        self.assertTrue(any("MAY be live" in m for m in logs.output))
        self.assertTrue(self._told("a close may be live"))

    def test_a_redirected_close_from_the_drain_is_held_and_never_sent_twice(self):
        """pending_closes.retry_trade_close on a CLOSE_PENDING eToro row
        whose position the book still lists: the close meets a 302, the row
        carries close_in_doubt, and the next pass, past the venue's lag,
        sends nothing ("may already be live")."""
        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import (CLOSE_IN_DOUBT_KEY,
                                                CLOSE_SENT_AT_KEY,
                                                retry_trade_close)
        _bot, trade = self._row(status="CLOSE_PENDING")
        held = {"clientPortfolio": {"positions": [{
            "positionID": 900001, "instrumentID": 1001, "isBuy": True,
            "units": 10.0, "orderID": 1000001}]}}
        venue = _Venue([SEARCH_AAPL, RATES,
                        ("GET", "/info/demo/portfolio", 200, held)],
                       redirects={("POST", CLOSE): (302, OTHER + "/c")})
        t = _client(venue)
        t.instrument_id("AAPL")        # the book names 1001 as AAPL
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"), \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertFalse(retry_trade_close(trade))
        [(_m, _u, sent)] = venue.to("POST", CLOSE)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSE_PENDING")
        self.assertEqual(trade.metadata[CLOSE_IN_DOUBT_KEY]["reference"],
                         sent["x-request-id"])
        # ten minutes on: the venue's lag (60 s) is past both stamps
        meta = dict(trade.metadata)
        later = (timezone.now() - timedelta(minutes=10)).isoformat()
        meta[CLOSE_SENT_AT_KEY] = meta["close_retry_last_at"] = later
        AssetBotTrade.objects.filter(pk=trade.pk).update(metadata=meta)
        trade.refresh_from_db()
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"), \
                self.assertLogs("bot_program.pending_closes", level="ERROR"):
            self.assertFalse(retry_trade_close(trade))
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a second close was sent on top of one in doubt")
        trade.refresh_from_db()
        self.assertIn("may already be live",
                      trade.metadata["close_blocked_why"])
        self.assertEqual(venue.at_other_hosts(), [])

    # ── EMERGENCY FLATTEN over a close the bot lane holds in doubt ──────
    # (2026-11-01, the S3 review). The bot lane's in-doubt branch leaves the
    # row OPEN with close_in_doubt and no close_order_working, so the kill
    # switch's working-close guard let it through and the switch sent the
    # row a second full close, then said "broker filled only 0.0".

    def _bot_lane_doubt(self, *routes):
        """The bot lane's redirected close, as
        test_a_redirected_close_from_the_bot_lane_is_held_in_doubt leaves
        it: one close POST, the row OPEN with close_in_doubt (its reference
        and `at`) and no close_order_working. The redirect was transient:
        from here the venue answers through `routes`."""
        bot, trade = self._row()
        venue = _Venue([SEARCH_AAPL, RATES, *routes], redirects={
            ("POST", CLOSE): (302, OTHER + "/c")})
        t = _client(venue)
        t.instrument_id("AAPL")
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="ERROR"), \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertFalse(bot._close_trade(trade, Decimal("205"), t,
                                              reason="TIME"))
        venue.redirects = {}
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["close_in_doubt"]["reference"])
        self.assertNotIn("close_order_working", trade.metadata)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1)
        return bot, trade, venue, t

    def _settle(self, trade, minutes=10):
        """`minutes` on: the close in doubt was sent that long ago, past the
        venue's lag (EtoroTrader.PORTFOLIO_LAG_S, 60 s)."""
        from bot_program.models import AssetBotTrade
        meta = dict(trade.metadata)
        meta["close_in_doubt"] = dict(
            meta["close_in_doubt"],
            at=(timezone.now() - timedelta(minutes=minutes)).isoformat())
        AssetBotTrade.objects.filter(pk=trade.pk).update(metadata=meta)
        trade.refresh_from_db()

    def _flatten(self, trade, t):
        from bot_program.engine.kill_switch import execute_kill_switch
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"), \
                self.assertLogs(KILL, level="ERROR"):
            return execute_kill_switch(user=trade.config.user,
                                       reason="the S3 review")

    def test_one_press_sends_no_second_close_over_either_lanes_close_in_doubt(self):
        """EMERGENCY FLATTEN with the book unreadable, over two eToro closes
        in doubt: one the switch's own close left (CLOSE_PENDING,
        close_order_working with no order id: the skeptic's V3), one the bot
        lane's (AssetBot._close_trade, through which the tick's exits, the
        CLOSE button, the TAKE TRADE funding closes, position_care and the
        options expiry all close: the row OPEN with close_in_doubt and no
        close_order_working). Neither gets a second close: the bot lane's
        row is named in the errors with its reference, and the switch's own
        row is refused by its working-close guard, exactly as before."""
        from bot_program.models import AssetBotTrade
        from tests.test_order_lifecycle import _bot, _open_trade
        user = User.objects.create_user("s3_two_lanes", password="x")
        bot, cfg = _bot(user)

        def row(position_id):
            trade = _open_trade(cfg, protective_trade_id=position_id,
                                broker="etoro", broker_env="paper",
                                initial_stop_loss=190.0)
            AssetBotTrade.objects.filter(pk=trade.pk).update(
                opened_at=timezone.now() - timedelta(days=1))
            trade.refresh_from_db()
            return trade

        venue = _Venue([SEARCH_AAPL, RATES], redirects={
            ("POST", CLOSE_OWN): (302, OTHER + "/c"),
            ("GET", PORTFOLIO): (302, OTHER + "/p")})
        t = _client(venue)
        t.instrument_id("AAPL")
        own = row("900002")
        first = self._flatten(own, t)
        own.refresh_from_db()
        self.assertEqual(own.status, "CLOSE_PENDING")
        self.assertTrue(own.metadata["close_in_doubt"])
        self.assertIs(own.metadata["close_order_working"], True)
        self.assertEqual(len(first["errors"]), 1)

        lane = row("900001")
        venue.redirects[("POST", CLOSE)] = (302, OTHER + "/c")
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="ERROR"), \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertFalse(bot._close_trade(lane, Decimal("205"), t,
                                              reason="TIME"))
        lane.refresh_from_db()
        ref = lane.metadata["close_in_doubt"]["reference"]
        self.assertNotIn("close_order_working", lane.metadata)

        res = self._flatten(lane, t)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a second close went over the bot lane's close in "
                         "doubt")
        self.assertEqual(len(venue.to("POST", CLOSE_OWN)), 1,
                         "a second close went over the switch's own close in "
                         "doubt")
        [said] = [e for e in res["errors"] if f"asset trade {lane.id} " in e]
        self.assertIn(f"a close may already be live at the venue under "
                      f"reference {ref}", said)
        self.assertIn("the switch sent NOTHING for it", said)
        self.assertIn("check the position at the venue", said)
        self.assertNotIn("filled only", said)
        [refused] = [e for e in res["errors"] if f"asset trade {own.id} " in e]
        self.assertIn("could not be cancelled", refused)
        lane.refresh_from_db()
        own.refresh_from_db()
        self.assertEqual(lane.status, "OPEN")
        self.assertEqual(lane.metadata["close_in_doubt"]["reference"], ref)
        self.assertEqual(own.status, "CLOSE_PENDING")
        self.assertTrue(own.metadata["close_in_doubt"])
        self.assertEqual(venue.at_other_hosts(), [])

    def test_a_book_that_cannot_be_read_sends_nothing(self):
        """The skeptic's V1: the book read is answered with a redirect too,
        so nothing says whether the close in doubt landed. One close POST
        in all, the row named in the errors with its reference, and never
        "broker filled only 0.0" (which may be false: the first close may
        have landed). The bot lane's own rule sends nothing here either."""
        _bot, trade, venue, t = self._bot_lane_doubt()
        ref = trade.metadata["close_in_doubt"]["reference"]
        venue.redirects = {("GET", PORTFOLIO): (302, OTHER + "/p")}
        with self.assertLogs(LOGGER, level="ERROR"):
            res = self._flatten(trade, t)
        self.assertEqual(len([s for s in venue.sent if s[0] == "POST"
                              and "market-close-orders" in s[1]]), 1,
                         "a second close went out over a book nobody read")
        self.assertEqual(len(venue.to("GET", PORTFOLIO)), 1)
        [said] = res["errors"]
        self.assertTrue(said.startswith(f"asset trade {trade.id} (AAPL): "),
                        said)
        self.assertIn(f"a close may already be live at the venue under "
                      f"reference {ref}", said)
        self.assertIn("the switch sent NOTHING for it", said)
        self.assertIn("check the position at the venue", said)
        self.assertNotIn("filled only", said)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"], ref)
        self.assertEqual(venue.at_other_hosts(), [])

    def test_a_book_that_lists_it_inside_the_lag_sends_nothing(self):
        """The book DOES list the position, read seconds after the close
        that did not come back: eToro's list keeps a closed position up to
        PORTFOLIO_LAG_S (measured 2026-09-23), so that read proves nothing.
        The lag runs from close_in_doubt.at, the one stamp the bot lane
        leaves. Nothing is sent and the marker stands."""
        _bot, trade, venue, t = self._bot_lane_doubt(LISTED)
        ref = trade.metadata["close_in_doubt"]["reference"]
        res = self._flatten(trade, t)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a second close went out on a read inside the lag")
        [said] = res["errors"]
        self.assertIn(f"under reference {ref}", said)
        self.assertIn("the switch sent NOTHING for it", said)
        self.assertIn("sent a close in doubt", said)
        self.assertIn("lags up to 60 s", said)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"], ref)

    def test_a_settled_book_that_lists_it_drops_the_marker_and_sends(self):
        """Past the lag, a book that still lists the position is the close
        in doubt NOT having landed: the marker goes, as AssetBot._close_trade
        drops it, and the switch sends its close as for any other row (here
        proven by the open order's read and booked CLOSED)."""
        _bot, trade, venue, t = self._bot_lane_doubt(LISTED)
        _lookup_router(venue.wire, by_order=[(200, _proof("open")),
                                             (200, _proof("closed"))])
        self._settle(trade)
        res = self._flatten(trade, t)
        self.assertEqual(res["errors"], [])
        self.assertEqual(len(venue.to("POST", CLOSE)), 2)
        trade.refresh_from_db()
        self.assertNotIn("close_in_doubt", trade.metadata)
        self.assertEqual(trade.metadata["close_in_doubt_resolved"],
                         "the broker still held it")
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(venue.at_other_hosts(), [])

    def test_a_settled_book_listing_less_than_the_row_sends_nothing(self):
        """AssetBot._close_trade's rule says "still held" only when the book
        holds the row's whole size (_broker_still_holds). A settled book
        listing four of the row's ten units says part of the close in doubt
        may have filled: that is no proof it did not land, so nothing is
        sent and the marker stands."""
        part = ("GET", PORTFOLIO, 200, {"clientPortfolio": {"positions": [{
            "positionID": 900001, "instrumentID": 1001, "isBuy": True,
            "units": 4.0, "orderID": 1000001}]}})
        _bot, trade, venue, t = self._bot_lane_doubt(part)
        self._settle(trade)
        res = self._flatten(trade, t)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a second close went out over a part-filled doubt")
        [said] = res["errors"]
        self.assertIn("the switch sent NOTHING for it", said)
        self.assertIn("part of the close in doubt may have filled", said)
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["close_in_doubt"])

    def test_the_venue_proving_it_closed_books_the_row_and_sends_nothing(self):
        """eToro's own order read (position_state by the OPEN order's id)
        says closed: the close in doubt LANDED. The row is booked the way
        the drain books it (pending_closes._finalise_flat on the venue's
        word, under the close claim), whatever its lagging list says, and
        no close is sent."""
        _bot, trade, venue, t = self._bot_lane_doubt(LISTED)
        _lookup_router(venue.wire, by_order=(200, _proof("closed")))
        res = self._flatten(trade, t)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["asset_positions_closed"], 1)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a second close went over a close the venue proved")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:KILL_SWITCH_VENUE_PROVED_CLOSED", trade.reason)
        self.assertIsNotNone(trade.exit_price)
        self.assertNotIn("manual_close_claim", trade.metadata)

    def test_a_settled_book_without_it_books_the_row_as_the_drain_does(self):
        """Past the lag, the book no longer lists the position and eToro's
        order read does not answer: the drain's rule (venue_exit). The
        first unanswered ask sends nothing and books nothing; an hour of
        unanswered asks on, the row is booked from the list and says so
        (venue_unproven_close). No close is sent either way."""
        from bot_program.models import AssetBotTrade
        _bot, trade, venue, t = self._bot_lane_doubt(UNLISTED)
        self._settle(trade)
        res = self._flatten(trade, t)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a second close went out over a book without it")
        [said] = res["errors"]
        self.assertIn("the switch sent NOTHING for it", said)
        self.assertIn("order read did not answer", said)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.metadata["close_in_doubt"])
        meta = dict(trade.metadata)
        now = timezone.now()
        meta["venue_miss"] = {
            "since": (now - timedelta(minutes=70)).isoformat(), "asks": 3,
            "last_at": (now - timedelta(minutes=5)).isoformat()}
        AssetBotTrade.objects.filter(pk=trade.pk).update(metadata=meta)
        trade.refresh_from_db()
        res = self._flatten(trade, t)
        self.assertEqual(res["errors"], [])
        self.assertEqual(len(venue.to("POST", CLOSE)), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:KILL_SWITCH_ALREADY_FLAT", trade.reason)
        self.assertIn("did not answer",
                      trade.metadata["venue_unproven_close"])

    def test_the_bot_lane_clears_its_marker_only_on_a_read_past_the_lag(self):
        """AssetBot._close_trade's own rule, e.g. the CLOSE button pressed
        right after the "a close may be live" alert: a book that lists the
        position seconds after the close that did not come back is the
        venue's lag, not that close having failed. The marker stands and
        nothing is sent. Past the lag the same read clears it and the close
        is sent, as before."""
        bot, trade, venue, t = self._bot_lane_doubt(LISTED)
        ref = trade.metadata["close_in_doubt"]["reference"]
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="WARNING") as logs:
            self.assertFalse(bot._close_trade(trade, Decimal("205"), t,
                                              reason="TIME"))
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "the marker was cleared on a read inside the lag")
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"], ref)
        self.assertTrue(any("inside the venue's lag" in m
                            for m in logs.output), logs.output)
        self._settle(trade)
        bot._tick_broker_cache = {}       # a later pass reads afresh
        with mock.patch("time.sleep"):
            bot._close_trade(trade, Decimal("205"), t, reason="TIME")
        self.assertEqual(len(venue.to("POST", CLOSE)), 2)
        trade.refresh_from_db()
        self.assertNotIn("close_in_doubt", trade.metadata)
        self.assertEqual(trade.metadata["close_in_doubt_resolved"],
                         "the broker still held it")

    # ── the CLOSE button over a close in doubt says what it did ─────────
    # (2026-11-01, the S3 review). manual_close.execute_close answered every
    # close the engine declined on a live row with "The broker rejected the
    # close ... the row is CLOSE_PENDING and the retry task will keep trying
    # every 5 minutes". Over a close in doubt none of it is true: nothing was
    # refused, the row stays OPEN, and the drain reads CLOSE_PENDING rows
    # only, so no retry comes back to it.

    #: Words that are false for a row left OPEN with a close in doubt.
    NOT_THERE = ("rejected", "CLOSE_PENDING", "retry task")

    def test_the_close_button_inside_the_lag_sends_nothing_and_says_so(self):
        """The CLOSE button pressed right after the "a close may be live"
        alert: the book lists the position, read inside the venue's lag, so
        nothing is sent and the marker stands. The answer says so (nothing
        sent, the row OPEN, a close may be live under its reference, in
        doubt, nothing pending), and the staff are told, since no retry
        task comes back to an OPEN row."""
        from bot_program.manual_close import execute_close
        _bot, trade, venue, t = self._bot_lane_doubt(LISTED)
        ref = trade.metadata["close_in_doubt"]["reference"]
        told = len(self.staff.call_args_list)
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="WARNING"):
            out = execute_close(trade.config.user, trade, pin_ok=True)
        self.assertEqual(len(venue.to("POST", CLOSE)), 1,
                         "a close went out on a read inside the lag")
        self.assertIs(out.get("in_doubt"), True, out)
        self.assertNotIn("pending", out)
        said = out["error"]
        self.assertTrue(said.startswith("NOTHING was sent for AAPL and the "
                                        "row stays OPEN: "), said)
        self.assertIn(f"a close sent earlier may already be live at the "
                      f"broker under reference {ref}", said)
        self.assertIn("check the position at the venue", said)
        for lie in self.NOT_THERE:
            self.assertNotIn(lie, said)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"], ref)
        self.assertNotIn("manual_close_claim", trade.metadata)
        [notice] = self.staff.call_args_list[told:]
        self.assertIn(f"under reference {ref}", str(notice))
        self.assertIn("read inside the venue's lag", str(notice))
        self.assertIn("NOTHING is being sent", str(notice))

    def test_the_close_button_whose_close_did_not_come_back_says_it_may_be_live(self):
        """The CLOSE button's own close meets a redirect: the close WAS sent
        and may be live. The answer says that (never "nothing was sent"),
        in doubt and nothing pending; the row stays OPEN with the marker,
        and the staff are told "a close may be live" as the bot lane tells
        them."""
        from bot_program.manual_close import execute_close
        _bot, trade = self._row()
        venue = _Venue([SEARCH_AAPL, RATES], redirects={
            ("POST", CLOSE): (302, OTHER + "/c")})
        t = _client(venue)
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="ERROR"), \
                self.assertLogs(LOGGER, level="ERROR"):
            out = execute_close(trade.config.user, trade, pin_ok=True)
        [(_m, _u, sent)] = venue.to("POST", CLOSE)
        ref = sent["x-request-id"]
        self.assertIs(out.get("in_doubt"), True, out)
        self.assertNotIn("pending", out)
        said = out["error"]
        self.assertTrue(said.startswith("The close of AAPL did not come back: "
                                        "it MAY be live at the broker under "
                                        f"reference {ref}"), said)
        self.assertIn("the row stays OPEN", said)
        self.assertIn("check the position at the venue", said)
        self.assertNotIn("NOTHING was sent", said)
        for lie in self.NOT_THERE:
            self.assertNotIn(lie, said)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["close_in_doubt"]["reference"], ref)
        self.assertTrue(self._told("a close may be live"))
        self.assertEqual(venue.at_other_hosts(), [])


# ── the demo proof client keeps its own refusal ─────────────────────────

class TheDemoClientTests(_Clean, SimpleTestCase):

    def test_its_wire_refuses_on_its_own_over_a_session_that_would_follow(self):
        """The wire (2026-10-31) forces allow_redirects off, sets
        max_redirects 0 and refuses a 3xx. Under it here is a PLAIN
        requests.Session, one that
        follows by default: still one request, to the demo segment, nothing
        at the other host, and its log says the status and the host only."""
        from bot_program.engine.etoro_client import DemoOnlyEtoroTrader
        for code in (302, 307, 300):
            with self.subTest(code=code):
                venue = _Venue(redirects={("POST", ORDERS): (code, ELSEWHERE)})
                t = DemoOnlyEtoroTrader("api-k", "user-k")
                plain = requests.Session()
                plain.headers.update({"x-api-key": "api-k",
                                      "x-user-key": "user-k"})
                plain.mount("https://", venue)
                t._session = plain
                with self.assertRaises(RedirectRefused) as cm, \
                        self.assertLogs(LOGGER, level="ERROR") as logs:
                    t._sess().post(t._v2_exec_orders(),
                                   json={"transaction": "sellShort"},
                                   allow_redirects=True, timeout=5)
                self.assertEqual((cm.exception.status, cm.exception.host),
                                 (code, OTHER_HOST))
                self.assertEqual(len(venue.sent), 1)
                self.assertEqual(venue.at_other_hosts(), [])
                self.assertEqual(plain.max_redirects, 0)
                self.assertEqual(t.wire_requests, 1)
                said = "\n".join(logs.output) + str(cm.exception)
                self.assertIn(OTHER_HOST, said)
                for never in ("elsewhere", "token", "api-k", "user-k"):
                    self.assertNotIn(never, said)

    def test_it_stands_on_the_refusing_session(self):
        from bot_program.engine.etoro_client import (DemoOnlyEtoroTrader,
                                                     NoRedirectSession)
        wire = DemoOnlyEtoroTrader("api-k", "user-k")._sess()
        self.assertIsInstance(wire._inner, NoRedirectSession)


# ── the requests.* sites outside the client ─────────────────────────────

class TheOtherSitesTests(_Clean, SimpleTestCase):

    def test_the_brokers_probe_follows_no_redirect(self):
        """dashboard/views_brokers.etoro_probe sends both keys with a
        requests.get of its own (the /brokers/ save): one request, nothing
        at the other host, "unknown" with the status and the host only."""
        from dashboard.views_brokers import etoro_probe
        venue = _Venue(redirects={("GET", "/info/demo/aggregate-portfolio"):
                                  (302, ELSEWHERE)})
        with mock.patch.object(requests.adapters.HTTPAdapter, "send",
                               side_effect=venue.send), \
                self.assertLogs("dashboard.views_brokers",
                                level="WARNING") as logs:
            state, detail = etoro_probe("api-k", "user-k")
        self.assertEqual(state, "unknown")
        self.assertIn("302", detail)
        self.assertIn(OTHER_HOST, detail)
        self.assertEqual(len(venue.sent), 1)
        self.assertEqual(venue.at_other_hosts(), [])
        said = "\n".join(logs.output) + detail
        for never in ("elsewhere", "token", "api-k", "user-k"):
            self.assertNotIn(never, said)

    def test_the_legacy_market_data_adapter_follows_no_redirect(self):
        from market_data.adapters import etoro_adapter
        host = urlsplit(etoro_adapter.BASE_URL).netloc
        venue = _Venue(redirects={("GET", "/api/v1/positions"):
                                  (302, ELSEWHERE)}, host=host)
        client = etoro_adapter.EtoroClient(api_key="api-k")
        client.session.mount("https://", venue)
        with self.assertLogs("market_data.adapters.etoro_adapter",
                             level="ERROR") as logs, \
                self.assertLogs(LOGGER, level="ERROR"):
            self.assertIsNone(client.get_positions())
        self.assertEqual(len(venue.sent), 1)
        self.assertEqual(venue.at_other_hosts(), [])
        self.assertFalse(any("elsewhere" in m for m in logs.output))


# ── the pin: a new eToro request site that follows redirects fails ──────

VERBS = frozenset({"get", "post", "put", "patch", "delete", "head",
                   "options", "request"})
#: EtoroTrader's URL builders (bot_program/engine/etoro_client.py).
URL_BUILDERS = frozenset({"_v1_info", "_v1_exec", "_v2", "_v2_info",
                          "_v2_lookup", "_v2_exec_orders", "_v3_exec_order"})
SKIP_DIRS = {"venv", ".venv", ".claude", "node_modules", ".git",
             "staticfiles", "static", "frontend", "test_backups", "SV_V",
             "__pycache__", "media", "logs", "tests", "migrations"}
CLIENT = "bot_program/engine/etoro_client.py"
#: The client's module name, however it is imported (2026-11-01).
CLIENT_MODULE = "etoro_client"
#: The eToro client's classes: a module that names one holds the client.
CLIENT_CLASSES = frozenset({"EtoroTrader", "DemoOnlyEtoroTrader",
                            "NoRedirectSession"})
#: The headers eToro's two keys ride on (EtoroTrader._sess).
KEY_HEADERS = ("x-api-key", "x-user-key")
#: The one session class allowed to subclass requests' own: the refusing
#: one, in the client itself, by name AND module.
EXEMPT_SESSION = (CLIENT, "NoRedirectSession")
URLLIB3_POOLS = frozenset({"PoolManager", "ProxyManager",
                           "HTTPConnectionPool", "HTTPSConnectionPool",
                           "connection_from_url", "proxy_from_url"})
#: What sends, or builds what sends, and follows a redirect by default, in
#: each general HTTP client the venv holds and the standard library's: name
#: -> the keyword whose literal False refuses it, or None when nothing does
#: (a session, pool, opener, agent or connection of its own). Surveyed over
#: the venv's 134 distributions (2026-11-01, the S3 review's second pass):
#: requests (pinned), aiohttp and websockets (pinned), urllib3, curl_cffi
#: (yfinance's), websocket-client (selenium's and praw's, module websocket),
#: aiohttp_retry (twilio's), Twisted's redirect agents (daphne's). httpx is
#: read by its own rule: its default follows none, and httpx2 and any other
#: client that takes follow_redirects by the "follow" rule. Not followers:
#: http.client, httpcore, h11 and wsproto (no redirect logic), trio_websocket
#: (a 3xx handshake is a ConnectionRejected). Left out: the wrappers built
#: on these for one provider or one format (praw and prawcore, twilio,
#: feedparser, yfinance, the market-data and model SDKs), which an eToro
#: module has no use for.
FOLLOWERS = {
    "requests": {**dict.fromkeys(VERBS, "allow_redirects"),
                 "Session": None, "session": None},
    "curl_cffi": {**dict.fromkeys(VERBS, "allow_redirects"),
                  **dict.fromkeys(("Session", "AsyncSession", "WebSocket",
                                   "AsyncWebSocket", "Curl", "AsyncCurl"))},
    "aiohttp": {"ClientSession": None, "request": "allow_redirects"},
    "aiohttp_retry": {"RetryClient": None},
    "urllib.request": dict.fromkeys(("urlopen", "Request", "build_opener")),
    "urllib3": {**dict.fromkeys(URLLIB3_POOLS), "request": "redirect"},
    "websockets": {"connect": None},
    "websocket": dict.fromkeys(("create_connection", "WebSocket",
                                "WebSocketApp")),
    "twisted.web.client": dict.fromkeys(("RedirectAgent",
                                         "BrowserLikeRedirectAgent")),
}
HTTP_MODULES = (*FOLLOWERS, "httpx")


def _production_modules():
    """(relative path, source) of every project module, pruning the trees
    that are not ours before they are walked. Every module, not only those
    that name requests (2026-11-01): the pin reads the other clients too."""
    root = Path(settings.BASE_DIR)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            try:
                src = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            yield path.relative_to(root).as_posix(), src


def _bindings(tree):
    """{name: every dotted target an import binds it to} for every import of
    the module, at any depth: `import requests.sessions as rs` binds rs to
    requests.sessions, `import requests.sessions` binds requests to
    requests, `from requests.sessions import Session as S` binds S to
    requests.sessions.Session, `from . import etoro_client` binds
    etoro_client to .etoro_client. EVERY target (2026-11-01, the S3
    review's second pass): one per name kept the last import ast.walk met,
    a function's own before the module's, so one `from curl_cffi import
    requests` in any function hid every real requests call of the module."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out.setdefault(a.asname, set()).add(a.name)
                else:
                    top = a.name.split(".")[0]
                    out.setdefault(top, set()).add(top)
        elif isinstance(node, ast.ImportFrom):
            base = "." * (node.level or 0) + (node.module or "")
            for a in node.names:
                if a.name != "*":
                    out.setdefault(a.asname or a.name, set()).add(
                        base + a.name if base.endswith(".")
                        else f"{base}.{a.name}")
    return out


def _is_getattr(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and bool(node.args))


def _paths(node, bindings):
    """Every dotted path an expression names through the imports (an alias
    resolved, every attribute after it kept), one per target its name is
    bound to, or [] when it names none. getattr(x, "name") is x.name, and
    getattr(x, y) with a name not written down is x.* (2026-11-01)."""
    attrs = []
    while isinstance(node, ast.Attribute):
        attrs.insert(0, node.attr)
        node = node.value
    if _is_getattr(node):
        name = node.args[1] if len(node.args) > 1 else None
        last = (name.value if isinstance(name, ast.Constant)
                and isinstance(name.value, str) else "*")
        return [".".join([p, last, *attrs])
                for p in _paths(node.args[0], bindings)]
    if not isinstance(node, ast.Name) or node.id not in bindings:
        return []
    return [".".join([t, *attrs]) for t in sorted(bindings[node.id])]


def _library(path):
    """The HTTP client a dotted path is in (HTTP_MODULES), or "". requests
    wherever it is reached from (2026-11-01, the S3 review's second pass): a
    `requests` segment before the last name is requests too, through another
    module's namespace (bot_program.engine.etoro_client.requests.get: the
    client imports it, so the name is there); curl_cffi.requests is
    curl_cffi's own."""
    for m in HTTP_MODULES:
        if path == m or path.startswith(m + "."):
            return m
    return "requests" if "requests" in path.split(".")[:-1] else ""


def _follower(path):
    """(library, keyword) when `path` names what sends, or builds what
    sends, and follows a redirect (FOLLOWERS): `keyword` is the one whose
    literal False refuses it, None when nothing does. A `*` last name
    (getattr with a name not written down) is any name of its library, so
    refused by that library's keyword when it has one. None otherwise."""
    names = FOLLOWERS.get(_library(path))
    if not names:
        return None
    last = path.rsplit(".", 1)[-1]
    if last == "*":
        return _library(path), next((k for k in names.values() if k), None)
    if last not in names:
        return None
    return _library(path), names[last]


def _imports_a_client(node, bindings):
    """A call that imports, by a name written down, an HTTP client or the
    eToro client (which holds requests) at run time: __import__("requests"),
    importlib.import_module("curl_cffi.requests"). 2026-11-01."""
    if not node.args or not isinstance(node.args[0], ast.Constant) \
            or not isinstance(node.args[0].value, str):
        return False
    if not ((isinstance(node.func, ast.Name) and node.func.id == "__import__")
            or "importlib.import_module" in _paths(node.func, bindings)):
        return False
    name = node.args[0].value
    return bool(_library(name)) or name.split(".")[-1] == CLIENT_MODULE


def _requests_calls(tree, module=""):
    """(line, kind, node) of every place that can send an HTTP request and
    follow a redirect (2026-11-01; widened by the S3 review's second pass),
    each name read through every import that binds it (_bindings), requests
    wherever it is reached from (_library):

      subclass  a class whose bases name a following class of FOLLOWERS (a
                requests or curl_cffi session, an aiohttp ClientSession, a
                RetryClient...); the one exemption is EXEMPT_SESSION, the
                client's own refusing session, by name in `module` (a path
                as _production_modules gives it);
      refuse:K  a following callable called, or handed to functools.partial
                and judged by the partial's own keywords, that a literal
                K=False refuses (K: one keyword, or several joined by ","):
                a requests or curl_cffi verb at any depth or imported by
                name, aiohttp.request (allow_redirects), urllib3.request
                (redirect);
      own       a following callable called, or handed to partial, that
                nothing refuses: a session, pool, opener, agent or
                connection of its own (urllib.request's opener re-sends
                every header but content-length and content-type);
      named     a following callable named and NOT called there: handed on
                (asyncio.to_thread, an executor's submit, run_in_executor),
                stored (an alias, a class attribute, a default_factory), or
                reached through getattr; it follows wherever it is called.
                Not judged: what isinstance and issubclass read, annotations
                (nothing is sent) and class bases (subclass, above);
      httpx     a call into httpx (its default follows none);
      follow    any other call that passes follow_redirects (an httpx or
                httpx2 client's own methods);
      hidden    a star import, or an HTTP client imported at run time by a
                name written down (_imports_a_client): what it binds is out
                of this pin's sight.
    """
    bindings = _bindings(tree)

    def followers(expr):
        return {f for p in _paths(expr, bindings) if (f := _follower(p))}

    def partial_target(call):
        return (call.args[0] if call.args
                and "functools.partial" in _paths(call.func, bindings)
                else None)

    # Not a reference of its own: a call's callee (judged as the call), a
    # partial's target (judged by the partial), what isinstance and
    # issubclass read, an annotation, a class base, an attribute's inner
    # part (its whole chain is judged once).
    skip = set()
    for node in ast.walk(tree):
        inner = []
        if isinstance(node, ast.Call):
            skip.add(id(node.func))
            target = partial_target(node)
            if target is not None:
                skip.add(id(target))
            if isinstance(node.func, ast.Name) \
                    and node.func.id in ("isinstance", "issubclass"):
                inner += node.args
        elif isinstance(node, ast.ClassDef):
            inner += node.bases
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner.append(node.returns)
        elif isinstance(node, (ast.arg, ast.AnnAssign)):
            inner.append(node.annotation)
        elif isinstance(node, ast.Attribute):
            skip.add(id(node.value))
        for sub in inner:
            if sub is not None:
                skip.update(id(n) for n in ast.walk(sub))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if (module, node.name) != EXEMPT_SESSION and any(
                    k is None for b in node.bases for _l, k in followers(b)):
                out.append((node.lineno, "subclass", node))
            continue
        if isinstance(node, ast.ImportFrom):
            if any(a.name == "*" for a in node.names):
                out.append((node.lineno, "hidden", node))
            continue
        if isinstance(node, ast.Call):
            target = partial_target(node)
            found = followers(node.func) or (
                followers(target) if target is not None else set())
            if found:
                keys = {k for _l, k in found}
                out.append((node.lineno, "own" if None in keys
                            else "refuse:" + ",".join(sorted(keys)), node))
            elif _imports_a_client(node, bindings):
                out.append((node.lineno, "hidden", node))
            elif any(_library(p) == "httpx"
                     for p in _paths(node.func, bindings)):
                out.append((node.lineno, "httpx", node))
            elif any(k.arg == "follow_redirects" for k in node.keywords):
                out.append((node.lineno, "follow", node))
            if not _is_getattr(node):
                continue
        elif not isinstance(node, (ast.Name, ast.Attribute)) \
                or not isinstance(node.ctx, ast.Load):
            continue
        if id(node) not in skip and followers(node):
            out.append((node.lineno, "named", node))
    return out


def _touches_etoro(tree):
    """Is this an eToro module (2026-11-01)? One that composes a URL on
    eToro's API (a string on eToro's domain, the client's BASE, one of its
    URL builders), imports the client in any form (from bot_program.engine
    import etoro_client [as x], import bot_program.engine.etoro_client
    [as x], from . import etoro_client, a name from it), names one of the
    client's classes, or holds the header name of one of eToro's keys."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            if ETORO_DOMAIN in low or any(h in low for h in KEY_HEADERS):
                return True
        elif isinstance(node, ast.Attribute):
            if node.attr in URL_BUILDERS or node.attr in CLIENT_CLASSES:
                return True
        elif isinstance(node, ast.Name) and node.id in CLIENT_CLASSES:
            return True
        elif isinstance(node, ast.Import):
            if any(a.name.split(".")[-1] == CLIENT_MODULE
                   for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[-1] == CLIENT_MODULE \
                    or any(a.name == CLIENT_MODULE or a.name in CLIENT_CLASSES
                           for a in node.names):
                return True
    return False


def _refuses(node, arg, *, default_follows=True):
    """Does this call pass `arg` so that no redirect is followed: the
    literal False, or (default_follows False) the argument left out."""
    for k in node.keywords:
        if k.arg == arg:
            return isinstance(k.value, ast.Constant) and k.value.value is False
    return not default_follows


def _offences(src, module=""):
    """Why each place of an eToro module that can send an HTTP request may
    follow a redirect (_requests_calls): a session, pool, opener, agent or
    connection of its own, a call that does not refuse one, a following
    callable named where it is not called, or names the pin cannot read.
    `module` is the path the source lives at (the client's own refusing
    session is exempt there). A module that is not an eToro module
    (_touches_etoro) is not this pin's."""
    tree = ast.parse(src)
    if not _touches_etoro(tree):
        return []
    out = []
    for line, kind, node in _requests_calls(tree, module):
        if kind in ("subclass", "named", "hidden"):
            what = ast.unparse(node) if kind != "subclass" else ""
            out.append(f"{line}: " + {
                "subclass": "a session class of its own follows redirects "
                            "(use etoro_client.NoRedirectSession)",
                "named": f"{what} is named, not called: it follows "
                         f"redirects with the caller's headers wherever it "
                         f"is called (send through "
                         f"etoro_client.NoRedirectSession)",
                "hidden": f"{what} binds names this pin cannot read (import "
                          f"each name by itself)"}[kind])
            continue
        call = ast.unparse(node.func)
        if node.args and call.rsplit(".", 1)[-1] == "partial":
            call = f"{ast.unparse(node.args[0])} handed to {call}"
        if kind.startswith("refuse:"):
            missing = [k for k in kind.split(":", 1)[1].split(",")
                       if not _refuses(node, k)]
            if missing:
                out.append(f"{line}: {call}() without "
                           + " and ".join(f"{k}=False" for k in missing))
        elif kind in ("httpx", "follow"):
            if not _refuses(node, "follow_redirects", default_follows=False):
                out.append(f"{line}: {call}() with follow_redirects that is "
                           f"not False")
        else:
            out.append(f"{line}: {call}() follows redirects with the "
                       f"caller's headers (send through "
                       f"etoro_client.NoRedirectSession)")
    return out


class ThePinTests(SimpleTestCase):

    def test_a_new_etoro_request_site_that_follows_redirects_fails_the_pin(self):
        """The pin bites on a new site in every spelling, lets a refusing
        one and a non-eToro call through — and the tree has no offender:
        the requests.* calls left in eToro modules are the /brokers/ probe
        and the Telegram eye's Bot API call (the module builds the eToro
        client for its margin line), and both refuse."""
        domain_url = f"https://api.{ETORO_DOMAIN}"
        for bad in (
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return requests.post(BASE + '/x', headers={'k': k})\n",
                "import requests\n"
                "def f(t):\n"
                "    return requests.get(t._v1_info('portfolio'),\n"
                "                        allow_redirects=True)\n",
                "import requests\n"
                f"URL = {domain_url!r}\n"
                "class C:\n"
                "    def __init__(self):\n"
                "        self.s = requests.Session()\n",
                "import requests as rq\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return rq.request('DELETE', BASE)\n",
                "from requests import get\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return get(BASE)\n",
                # 2026-11-01, the S3 review: the spellings the pin missed.
                # The client imported as a module, in each form, BASE read
                # on the name it is bound to:
                "import requests\n"
                "from bot_program.engine import etoro_client as ec\n"
                "def f(k, u):\n"
                "    return requests.get(ec.BASE + '/api/v1/x',\n"
                "                        headers={'x-api-key': k,\n"
                "                                 'x-user-key': u})\n",
                "import requests\n"
                "from bot_program.engine import etoro_client\n"
                "def f(k):\n"
                "    return requests.post(etoro_client.BASE + '/api/v1/x',\n"
                "                         headers={'x-api-key': k})\n",
                "import requests\n"
                "import bot_program.engine.etoro_client as ec\n"
                "def f():\n"
                "    return requests.post(ec.BASE + '/x')\n",
                "import requests\n"
                "import bot_program.engine.etoro_client\n"
                "def f():\n"
                "    return requests.post(bot_program.engine.etoro_client.BASE)\n",
                "import requests\n"
                "from . import etoro_client\n"
                "def f():\n"
                "    return requests.post(etoro_client.BASE + '/x')\n",
                "import requests\n"
                "from bot_program.engine import etoro_client as ec\n"
                "def f():\n"
                "    s = requests.Session()\n"
                "    return s.get(ec.BASE + '/x')\n",
                # a verb deeper than requests.<verb>:
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return requests.api.get(BASE)\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return requests.api.post(BASE + '/x')\n",
                # the session class by its own module, by name or aliased:
                "from requests.sessions import Session\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return Session().post(BASE + '/x')\n",
                "import requests.sessions as rs\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return rs.Session().post(BASE)\n",
                # a session class of its own:
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "class S(requests.Session):\n"
                "    pass\n"
                "def f():\n"
                "    return S().get(BASE)\n",
                # the eToro client's own class name outside the client
                # follows requests' default like any other:
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "class NoRedirectSession(requests.Session):\n"
                "    pass\n",
                # the URL in a variable, eToro's two key headers beside it:
                "import requests\n"
                "def f(url, k, u):\n"
                "    return requests.get(url, headers={'x-api-key': k,\n"
                "                                      'x-user-key': u})\n",
                # a module that names an eToro client class:
                "import requests\n"
                "from bot_program import short_proofs\n"
                "def f(url):\n"
                "    short_proofs.DemoOnlyEtoroTrader('k', 'u')\n"
                "    return requests.get(url)\n",
                # the other HTTP clients the venv holds, each of which
                # follows a redirect with the caller's headers:
                "import urllib.request\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return urllib.request.urlopen(urllib.request.Request(\n"
                "        BASE + '/x', headers={'x-api-key': k}))\n",
                "from urllib.request import Request\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return Request(BASE + '/x')\n",
                "import aiohttp\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return aiohttp.ClientSession(\n"
                "        headers={'x-api-key': k}).get(BASE)\n",
                "import aiohttp\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f(k):\n"
                "    async with aiohttp.ClientSession(\n"
                "            headers={'x-api-key': k}) as s:\n"
                "        return await s.get(BASE)\n",
                "import aiohttp\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f():\n"
                "    async with aiohttp.request('GET', BASE) as r:\n"
                "        return await r.read()\n",
                "import httpx\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return httpx.get(BASE, follow_redirects=True)\n",
                "import httpx\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    with httpx.Client(follow_redirects=True) as c:\n"
                "        return c.get(BASE)\n",
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(client):\n"
                "    return client.get(BASE, follow_redirects=True)\n",
                "import urllib3\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return urllib3.PoolManager().request('GET', BASE)\n",
                "import urllib3\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return urllib3.request('GET', BASE)\n",
                "import websockets\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f():\n"
                "    return await websockets.connect(BASE)\n",
                # 2026-11-01, the S3 review's second pass. requests reached
                # through another module's namespace, and a name a local
                # import binds twice (the map kept one target per name):
                "from curl_cffi import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k, u):\n"
                "    return requests.get(BASE + '/x',\n"
                "                        headers={'x-api-key': k,\n"
                "                                 'x-user-key': u})\n",
                "from bot_program.engine.etoro_client import BASE, requests\n"
                "def f(k, u):\n"
                "    return requests.get(BASE + '/x',\n"
                "                        headers={'x-api-key': k,\n"
                "                                 'x-user-key': u})\n",
                "from bot_program.engine import etoro_client as ec\n"
                "def f(k):\n"
                "    return ec.requests.get(ec.BASE + '/x',\n"
                "                           headers={'x-api-key': k})\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def rates(k):\n"
                "    return requests.get(BASE + '/x',\n"
                "                        headers={'x-api-key': k})\n"
                "def scrape():\n"
                "    from curl_cffi import requests\n"
                "    return requests.get('https://example.invalid/x',\n"
                "                        allow_redirects=False)\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def scrape():\n"
                "    from curl_cffi import requests\n"
                "    return requests.get('https://example.invalid/x',\n"
                "                        allow_redirects=False)\n"
                "def rates(k):\n"
                "    return requests.get(BASE + '/x',\n"
                "                        headers={'x-api-key': k})\n",
                # the clients the venv holds beside the six (curl_cffi for
                # yfinance, websocket-client for selenium and praw,
                # aiohttp_retry for twilio, Twisted's agents for daphne),
                # each following a redirect with the caller's headers:
                "import curl_cffi\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return curl_cffi.get(BASE)\n",
                "import curl_cffi.requests as cr\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return cr.Session(headers={'x-api-key': k}).post(BASE)\n",
                "from curl_cffi.requests import AsyncSession\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f(k):\n"
                "    async with AsyncSession(headers={'x-api-key': k}) as s:\n"
                "        return await s.get(BASE + '/x')\n",
                "import curl_cffi\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return curl_cffi.WebSocket().connect(\n"
                "        BASE + '/ws', headers={'x-api-key': k})\n",
                "import websocket\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return websocket.create_connection(\n"
                "        BASE.replace('https', 'wss') + '/ws',\n"
                "        header={'x-api-key': k})\n",
                "from websocket import WebSocketApp\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    return WebSocketApp(BASE + '/ws', header={'x-api-key': k})\n",
                "import websocket\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return websocket.WebSocket().connect(BASE + '/ws')\n",
                "from aiohttp_retry import RetryClient\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f(k):\n"
                "    async with RetryClient(headers={'x-api-key': k}) as c:\n"
                "        return await c.get(BASE + '/x')\n",
                "from twisted.web.client import Agent, RedirectAgent\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(reactor, headers):\n"
                "    return RedirectAgent(Agent(reactor)).request(\n"
                "        b'GET', BASE.encode(), headers)\n",
                # a following callable named, not called there: handed on,
                # stored, or reached through getattr:
                "import asyncio\n"
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f(k):\n"
                "    return await asyncio.to_thread(\n"
                "        requests.get, BASE + '/x', headers={'x-api-key': k})\n",
                "import asyncio\n"
                "import functools\n"
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "async def f(k, body):\n"
                "    loop = asyncio.get_running_loop()\n"
                "    return await loop.run_in_executor(None, functools.partial(\n"
                "        requests.post, BASE + '/x', json=body,\n"
                "        headers={'x-api-key': k}))\n",
                "from functools import partial\n"
                "import requests\n"
                "from django.db import transaction\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k, body):\n"
                "    transaction.on_commit(partial(\n"
                "        requests.post, BASE + '/x', json=body,\n"
                "        headers={'x-api-key': k}))\n",
                "from concurrent.futures import ThreadPoolExecutor\n"
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(k):\n"
                "    with ThreadPoolExecutor() as pool:\n"
                "        return pool.submit(requests.get, BASE + '/x',\n"
                "                           headers={'x-api-key': k}).result()\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(method, path, k):\n"
                "    return getattr(requests, method.lower())(\n"
                "        BASE + path, headers={'x-api-key': k})\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "fetch = getattr(requests, 'get')\n"
                "def f():\n"
                "    return fetch(BASE)\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "fetch = requests.get\n"
                "def f(k):\n"
                "    return fetch(BASE + '/x', headers={'x-api-key': k})\n",
                "import requests\n"
                "from dataclasses import dataclass, field\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "@dataclass\n"
                "class Feed:\n"
                "    http: requests.Session = field(\n"
                "        default_factory=requests.Session)\n"
                "    def rates(self):\n"
                "        return self.http.get(BASE + '/x')\n",
                "import aiohttp\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "class Feed:\n"
                "    session_cls = aiohttp.ClientSession\n"
                "    async def rates(self, k):\n"
                "        async with self.session_cls(\n"
                "                headers={'x-api-key': k}) as s:\n"
                "            return await s.get(BASE + '/x')\n",
                "import aiohttp\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "class S(aiohttp.ClientSession):\n"
                "    pass\n"
                "async def f():\n"
                "    async with S() as s:\n"
                "        return await s.get(BASE)\n",
                # names this pin cannot see: a star import, an import at run
                # time by name:
                "from requests import *\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return get(BASE)\n",
                "from bot_program.engine.etoro_client import *\n"
                "def f():\n"
                "    return requests.get(BASE)\n",
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return __import__('requests').get(BASE + '/x')\n",
                "import importlib\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return importlib.import_module('requests').get(BASE)\n"):
            with self.subTest(src=bad):
                self.assertTrue(_offences(bad), bad)
        for good in (
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return requests.get(BASE, allow_redirects=False)\n",
                "import requests\n"
                "def f():\n"
                "    return requests.get('https://example.invalid/x')\n",
                "from bot_program.engine.etoro_client import BASE\n"
                "from bot_program.engine.etoro_client import "
                "NoRedirectSession\n"
                "def f():\n"
                "    return NoRedirectSession().get(BASE)\n",
                "from bot_program.engine import etoro_client as ec\n"
                "class S(ec.NoRedirectSession):\n"
                "    pass\n"
                "def f():\n"
                "    return S().get(ec.BASE)\n",
                "import requests\n"
                "from bot_program.engine import etoro_client as ec\n"
                "def f():\n"
                "    return requests.api.get(ec.BASE, allow_redirects=False)\n",
                "import httpx\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return httpx.get(BASE)\n",
                "import urllib3\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return urllib3.request('GET', BASE, redirect=False)\n",
                "import aiohttp\n"
                "async def f():\n"
                "    async with aiohttp.ClientSession() as s:\n"
                "        return await s.get('https://example.invalid/x')\n",
                # 2026-11-01, the S3 review's second pass: what refuses, and
                # what sends nothing, in the new spellings.
                "from functools import partial\n"
                "import requests\n"
                "from django.db import transaction\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(body):\n"
                "    transaction.on_commit(partial(\n"
                "        requests.post, BASE + '/x', json=body,\n"
                "        allow_redirects=False))\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f(method, path):\n"
                "    return getattr(requests, method.lower())(\n"
                "        BASE + path, allow_redirects=False)\n",
                "from curl_cffi import requests\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "def f():\n"
                "    return requests.get(BASE, allow_redirects=False)\n",
                "import requests\n"
                "from bot_program.engine.etoro_client import (BASE,\n"
                "                                             NoRedirectSession)\n"
                "def f(s: requests.Session) -> requests.Session:\n"
                "    if not isinstance(s, requests.Session):\n"
                "        s = NoRedirectSession()\n"
                "    try:\n"
                "        s.get(BASE)\n"
                "    except requests.exceptions.RequestException:\n"
                "        pass\n"
                "    return s\n",
                "import httpx\n"
                "from dataclasses import dataclass, field\n"
                "from bot_program.engine.etoro_client import BASE\n"
                "@dataclass\n"
                "class Feed:\n"
                "    http: httpx.Client = field(default_factory=httpx.Client)\n"
                "    def rates(self):\n"
                "        return self.http.get(BASE)\n"):
            with self.subTest(src=good):
                self.assertEqual(_offences(good), [])
        # The one exemption is the client's own refusing session, by its
        # name AND its module: the same class anywhere else is a session of
        # its own.
        client_src = (Path(settings.BASE_DIR) / CLIENT).read_text(
            encoding="utf-8")
        self.assertEqual(
            [kind for _l, kind, _n in _requests_calls(ast.parse(client_src))],
            ["subclass"])
        offenders, sites = [], []
        for rel, src in _production_modules():
            found = _offences(src, rel)
            offenders += [f"{rel}:{why}" for why in found]
            if _touches_etoro(ast.parse(src)) \
                    and _requests_calls(ast.parse(src), rel):
                sites.append(rel)
        self.assertEqual(offenders, [])
        self.assertEqual(sorted(sites), ["bot_program/telegram_eye.py",
                                         "dashboard/views_brokers.py"])

    def test_the_client_sends_only_through_the_session_it_builds(self):
        """In the client itself: no requests session of its own and no
        requests.* call, every allow_redirects it passes is False, and
        self._session is written only where the refusing one is built."""
        src = (Path(settings.BASE_DIR) / CLIENT).read_text(encoding="utf-8")
        tree = ast.parse(src)
        self.assertEqual([(line, kind) for line, kind, _n
                          in _requests_calls(tree, CLIENT)], [])
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "allow_redirects":
                self.assertIs(getattr(node.value, "value", None), False,
                              ast.unparse(node))
        writers = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) \
                        and node.attr == "_session" \
                        and isinstance(node.ctx, ast.Store):
                    writers.add(fn.name)
        self.assertEqual(writers, {"__init__", "_sess"})
        [sess] = [n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_sess"
                  and "NoRedirectSession" in ast.unparse(n)]
        self.assertIn("NoRedirectSession()", ast.unparse(sess))
