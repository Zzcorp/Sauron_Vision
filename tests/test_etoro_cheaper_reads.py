"""CHEAPER eTORO READS (2026-11-01): pooled read connections, the pool check
from the sync's own equity, offset beats, one book per reconcile pass, and
the three zero gaps.

  * THE READ POOL (etoro_client.READ_POOL): a GET the budget may refuse (P2
    to P5) rides ONE pooled requests.Session per process and user key (its
    short hash), shared by every client of that key. The manage tick's
    marks and proposals (P3, P4) take (connect 4 s, read 10 s) on it; the
    account reads (P2) and the candles (P5) keep the client's own timeout,
    so a connect of 4 to 10 s that answered before still answers there
    (no missed sync, no live series sent to the public feed and muted for
    six hours). Every write (the order POST, the close POST, the PATCH,
    the DELETE), the orders:lookup, ping, the eligibility POST and every
    read at P0 or P1 keep the client's own session and today's timeout. A
    pooled GET that fails on a stale socket is retried once on a fresh
    connection, inside today's single retry, never as a third attempt.
  * THE POOL CHECK (capital_truth.broker_equity): an eToro config reads the
    account's equity as the sync stored it, under 15 minutes old, read in
    the world the row trades; anything else is None ("not measured"), and
    nothing is sent. The reading and its age, or why none stands, are said
    at INFO (production's level) once per user, reason and 15 minutes, and
    at DEBUG in between.
  * THE BEATS: the eToro sync at minute 1 of every five, the reconcile at
    minute 3; the bot tick stays the 300 s interval it was.
  * ONE BOOK PER PASS: the reconcile's row walk and its unclaimed sweep read
    eToro's /portfolio once per user and world, each naming the rows with
    its own warm; the sweep's grace runs from that read.
  * THE ZERO GAPS: the legacy lane never manages (and so never closes) a
    LIVE row at a price of 0, below it or unreadable; manage.py treasury
    prints a dash for a mark nobody read; etoro_smoke sends one request a
    second, at P5.

Run with:  python manage.py test tests.test_etoro_cheaper_reads
"""
import os
import urllib.request
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program.engine import etoro_budget as eb
from bot_program.engine import etoro_client as ec
from tests import test_bars_etoro_quota as bq
from tests.test_etoro_client import _Resp, _clear_eligibility, _lookup

USER_KEY = "user-k"
KH = eb.key_hash(USER_KEY)
ROUTER = "bot_program.engine.broker_router.client_for_symbol"
CLOSED = _lookup(3)
CLOSED["positionExecutions"][0]["state"] = "closed"
WAITING = {"status": {"id": 11, "name": "WaitingForMarket", "errorCode": 0}}
CANCELED = {"status": {"id": 7, "name": "Canceled", "errorCode": 0}}
AGG = {"accountCurrency": "USD", "accountTotals": {
    "accountTotalValue": 1000.0, "accountAvailableCash": 400.0,
    "accountTotalUsedMargin": 600.0}}
BOOK = {"positions": [
    {"instrumentID": 1001, "units": 1.0, "isBuy": True, "positionID": 999},
    {"instrumentID": 1002, "units": 2.0, "isBuy": True, "positionID": 1000}]}


def _routes():
    """(method, substring of "url?k=v&", answers): each answer is a
    (status, payload); a list of several is played in order, its last
    repeating. The params are folded into the probe, each ended by "&", so
    two /search spellings answer apart."""
    return [
        ("GET", "search?internalSymbolFull=AAPL&",
         [(200, [{"instrumentId": 1001, "internalSymbolFull": "AAPL"}])]),
        ("GET", "search?internalSymbolFull=MSFT&",
         [(200, [{"instrumentId": 1002, "internalSymbolFull": "MSFT"}])]),
        ("GET", "/rates", [(200, {"rates": [
            {"bid": 99.9, "ask": 100.1, "lastExecution": 100.0}]})]),
        ("GET", "/aggregate-portfolio", [(200, AGG)]),
        ("GET", "/info/portfolio", [(200, BOOK)]),
        ("GET", "/history/candles", [(200, {"candles": []})]),
        ("GET", "orders:lookup", [(200, _lookup(3)), (200, CLOSED),
                                  (200, WAITING), (200, CANCELED)]),
        ("POST", "/execution/orders", [(200, {"orderId": 77})]),
        ("POST", "market-close-orders", [(200, {"orderForClose": {
            "orderID": 9}})]),
        ("POST", "/eligibility", [(200, {"currency": "usd",
                                         "eligibilities": []})]),
        ("PATCH", "/positions/", [(200, {})]),
        ("DELETE", "/orders/", [(202, {})]),
    ]


class _Wire:
    """A requests.Session stand-in: every call is logged with the wire it
    was made on, answered from the shared routes; `fail` holds transport
    errors raised, in order, before any route is read."""

    def __init__(self, routes, log):
        self.routes, self.log = routes, log
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.closed = False
        self.fail = []

    def _hit(self, method, url, **kw):
        self.log.append((self, method, url, kw))
        if self.fail:
            raise self.fail.pop(0)
        params = kw.get("params") or {}
        probe = url + "?" + "".join(f"{k}={v}&"
                                    for k, v in sorted(params.items()))
        for m, sub, answers in self.routes:
            if m == method and sub in probe:
                status, payload = (answers[0] if len(answers) == 1
                                   else answers.pop(0))
                return _Resp(status, payload)
        return _Resp(200, {})

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def patch(self, url, **kw):
        return self._hit("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._hit("DELETE", url, **kw)

    def close(self):
        self.closed = True


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class _PoolOn:
    """The read pool ON over an empty pool; every requests.Session the
    adapter builds (its own and the pool's) is a _Wire from one factory, on
    one log; time.sleep a no-op. `fail_next` arms the NEXT wire built."""

    def setUp(self):
        super().setUp()
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        p = mock.patch.object(ec, "READ_POOL", True)
        p.start()
        self.addCleanup(p.stop)
        ec._POOL.clear()
        self.addCleanup(ec._POOL.clear)
        self.routes, self.log, self.made, self.fail_next = (
            _routes(), [], [], [])

        def make():
            w = _Wire(self.routes, self.log)
            w.fail, self.fail_next = list(self.fail_next), []
            self.made.append(w)
            return w
        p = mock.patch.object(ec.requests, "Session", side_effect=make)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def _client(self, *, user_key=USER_KEY, env="live", **kw):
        return ec.EtoroTrader("api-k", user_key, env=env, **kw)

    def _pool(self, kh=KH):
        return ec._POOL[kh][0]


class _SlowConnect:
    """A requests.Session stand-in whose every connection takes CONNECT_S
    to open, inside the 4 to 10 s band: a request whose connect timeout is
    shorter raises ConnectTimeout, as urllib3's does, and any other is
    answered by `inner`. Each attempt is logged as (method, url,
    timeout)."""

    CONNECT_S = 6.0

    def __init__(self, inner, log):
        self.inner, self.log = inner, log
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.closed = False

    def _go(self, method, url, **kw):
        t = kw.get("timeout")
        self.log.append((method, url, t))
        connect = t[0] if isinstance(t, tuple) else t
        if connect is not None and float(connect) < self.CONNECT_S:
            raise requests.exceptions.ConnectTimeout(
                f"no connection within {connect} s")
        return getattr(self.inner, method)(url, **kw)

    def get(self, url, **kw):
        return self._go("get", url, **kw)

    def post(self, url, **kw):
        return self._go("post", url, **kw)

    def close(self):
        self.closed = True


class _RowsFeed:
    """The keyless feed, with two hourly bars for every series: what the
    bar refresh writes, and mutes eToro for, when eToro gave none."""
    _sv_public_feed = True

    def __init__(self):
        self.calls = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval))
        now = int(timezone.now().timestamp() * 1000) // 3_600_000 * 3_600_000
        return [[now - 3_600_000 * i, "1.1", "1.2", "1.0", "1.15", "5",
                 now - 3_600_000 * i + 3_600_000, "0", 0, "0", "0", "0"]
                for i in (1, 0)]


# ── the read pool ─────────────────────────────────────────────────────────

class TheSuiteSwitchTests(SimpleTestCase):

    def test_the_suite_runs_with_the_pool_off(self):
        """The suite's fake wires ride each client's own session, as every
        read did before the pool; this module turns the pool on."""
        self.assertIs(ec.READ_POOL, False)
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_client.READ_POOL = False", src)

    def test_the_constants(self):
        self.assertEqual((ec.READ_CONNECT_TIMEOUT_S, ec.READ_TIMEOUT_S),
                         (4.0, 10.0))
        self.assertEqual(ec.READ_POOL_IDLE_S, 30.0)
        # the 4 s connect is the manage tick's marks' and proposals' alone
        self.assertEqual(ec.SHORT_CONNECT_AT, frozenset({eb.P3, eb.P4}))


class TheReadPoolTests(_PoolOn, SimpleTestCase):

    def test_a_mark_rides_the_pool_with_the_read_timeouts(self):
        t = self._client()
        with eb.at(eb.P3, "mark"):
            tk = t.ticker("AAPL")
        self.assertEqual(float(tk["lastPrice"]), 100.0)
        pool = self._pool()
        self.assertEqual([(w is pool, m) for w, m, _u, _k in self.log],
                         [(True, "GET"), (True, "GET")])
        for _w, _m, _u, kw in self.log:
            self.assertEqual(kw["timeout"], (4.0, 10.0))
            # the client's own keys ride each request: the pooled Session
            # carries none of its own
            self.assertEqual(kw["headers"]["x-api-key"], "api-k")
            self.assertEqual(kw["headers"]["x-user-key"], USER_KEY)
            self.assertEqual(kw["headers"]["Content-Type"],
                             "application/json")
            self.assertTrue(kw["headers"]["x-request-id"])
        self.assertEqual(pool.headers, {})
        self.assertIsNone(t._session, "the client built no session of its "
                                      "own for its reads")

    def test_a_proposal_takes_the_short_connect_as_a_mark_does(self):
        """The manage tick's marks (P3) and proposals (P4) take (4, 10): a
        failing connect holds the tick about 9 s with its retry, not 21."""
        t = self._client()
        with eb.at(eb.P4, "proposal"):
            t.ticker("AAPL")
        pool = self._pool()
        self.assertEqual([w is pool for w, *_ in self.log], [True, True])
        self.assertEqual({kw["timeout"] for *_x, kw in self.log},
                         {(4.0, 10.0)})

    def test_an_account_read_keeps_todays_timeout_on_the_pool(self):
        """The account reads (P2: the sync, the re-read, the reconcile,
        Telegram /status, the digests) share the pooled connection and keep
        the client's own timeout: a connect of 4 to 10 s that answered
        before still answers, so a slow connect never makes the sync miss
        its pass (2026-11-01, review)."""
        t = self._client()
        with eb.at(eb.P2, "account sync"):
            t.account()
        (w, _m, _u, kw), = self.log
        self.assertIs(w, self._pool())
        self.assertEqual(kw["timeout"], 10.0)

    def test_the_candles_keep_todays_timeout_on_the_pool(self):
        """The candles (P5), the /search of a cold id inside them included,
        keep the client's own timeout on the pooled connection: a live
        config's series stays eToro's through a connect that answered
        before (2026-11-01, review)."""
        t = self._client()
        t.klines("AAPL", "1h", 5)
        pool = self._pool()
        self.assertEqual([(w is pool, "search" in u)
                          for w, _m, u, _k in self.log],
                         [(True, True), (True, False)])
        self.assertEqual({kw["timeout"] for *_x, kw in self.log}, {10.0})

    def test_every_client_of_one_key_shares_one_pooled_session(self):
        """The router builds a new client per call: the second reads on
        the first's connection. Another key has its own pool."""
        a, b = self._client(), self._client()
        with eb.at(eb.P2, "account sync"):
            a.account()
            b.account()
        pool = self._pool()
        self.assertEqual([w for w, *_ in self.log], [pool, pool])
        other = self._client(user_key="another-k")
        with eb.at(eb.P2, "account sync"):
            other.account()
        theirs = self._pool(eb.key_hash("another-k"))
        self.assertIsNot(theirs, pool)
        self.assertIs(self.log[-1][0], theirs)
        self.assertEqual(self.log[-1][3]["headers"]["x-user-key"],
                         "another-k")
        self.assertFalse(any("another-k" in str(k) for k in ec._POOL),
                         "the pool is keyed by the key's hash, never the key")

    def test_every_write_keeps_its_own_session_and_todays_timeout(self):
        """The order POST, the close POST, the PATCH and the DELETE never
        touch the pooled session, nor do their lookups: a stale pooled
        socket failing after the send would make an order IN DOUBT."""
        t = self._client()
        with eb.at(eb.P3, "mark"):
            t.ticker("AAPL")
        pool = self._pool()
        t.market_order("AAPL", "BUY", 1.0, stop_loss=90.0, take_profit=110.0)
        t.close_position("555", "AAPL", 1.0, open_order_id="77")
        self.assertTrue(t.modify_protective("555", 95.0)["ok"])
        self.assertIs(t.cancel_order("88"), True)
        own = t._session
        self.assertIsNotNone(own)
        self.assertIsNot(own, pool)
        methods = {m for _w, m, _u, _k in self.log}
        self.assertEqual(methods, {"GET", "POST", "PATCH", "DELETE"})
        for w, m, url, kw in self.log:
            if w is pool:
                self.assertEqual(m, "GET", url)
                self.assertNotIn("orders:lookup", url)
            if m != "GET" or "orders:lookup" in url:
                self.assertIs(w, own, (m, url))
                self.assertEqual(kw["timeout"], 10.0, (m, url))
        self.assertEqual(t.timeout, 10.0)
        self.assertEqual(
            sum(1 for w, m, u, _k in self.log
                if w is own and "orders:lookup" in u), 4)

    def test_a_close_inside_the_marks_scope_never_reaches_the_pool(self):
        """The manage walk prices at P3 and closes inside that scope: the
        close sets P0 itself, so the /search a cold id costs rides the
        close's own session too."""
        t = self._client()
        with eb.at(eb.P3, "mark"):
            t.ticker("AAPL")
            n = len(self.log)
            t.close_position("556", "MSFT", 2.0)
        sent = self.log[n:]
        self.assertEqual([(m, "search" in u, "market-close" in u)
                          for _w, m, u, _k in sent],
                         [("GET", True, False), ("POST", False, True)])
        self.assertTrue(all(w is t._session for w, *_ in sent))

    def test_p0_and_p1_reads_keep_todays_connection_and_timeout(self):
        """The closes' marks (P0) and the last look or any read no caller
        classified (P1) are never refused nor delayed: they keep the
        client's own session, where a stale pooled socket cannot cost them
        the retry's wait."""
        t = self._client()
        with eb.at(eb.P0, "close"):
            t.ticker("AAPL")
        t.ticker("AAPL")
        self.assertNotIn(KH, ec._POOL)
        self.assertEqual(len(self.log), 3)            # one /search, 2 rates
        for w, _m, _u, kw in self.log:
            self.assertIs(w, t._session)
            self.assertEqual(kw["timeout"], 10.0)

    def test_the_eligibility_post_is_no_pooled_read(self):
        """A read, but a POST: only GETs ride the pool."""
        t = self._client()
        with eb.at(eb.P2, "eligibility"):
            t.eligibility("AAPL")
        pool = self._pool()
        (search_on, *_rest), = [c for c in self.log if c[1] == "GET"]
        self.assertIs(search_on, pool, "its /search is a P2 GET")
        (w, _m, url, kw), = [c for c in self.log if c[1] == "POST"]
        self.assertIn("/eligibility", url)
        self.assertIs(w, t._session)
        self.assertEqual(kw["timeout"], 10.0)

    def test_a_stale_pooled_socket_is_retried_once_on_a_fresh_connection(
            self):
        t = self._client()
        with eb.at(eb.P2, "account sync"):
            t.account()
        stale = self._pool()
        stale.fail = [requests.exceptions.ConnectionError(
            "('Connection aborted.', RemoteDisconnected('Remote end closed "
            "connection without response'))")]
        n = len(self.log)
        with mock.patch.object(t, "_note_health") as noted:
            with eb.at(eb.P2, "account sync"):
                info = t.account()
        self.assertEqual(info, AGG)
        sent = self.log[n:]
        self.assertEqual(len(sent), 2, "today's one retry, never a third")
        fresh = self._pool()
        self.assertIs(sent[0][0], stale)
        self.assertIsNot(fresh, stale)
        self.assertIs(sent[1][0], fresh)
        self.assertTrue(stale.closed, "the stale session's sockets closed")
        # an account read keeps today's timeout on the fresh connection too
        self.assertEqual(sent[1][3]["timeout"], 10.0)
        noted.assert_not_called()
        # the next read rides the fresh connection
        with eb.at(eb.P2, "account sync"):
            t.account()
        self.assertIs(self.log[-1][0], fresh)

    def test_a_marks_retry_on_a_fresh_connection_keeps_the_short_connect(
            self):
        t = self._client()
        with eb.at(eb.P3, "mark"):
            t.ticker("AAPL")
        stale = self._pool()
        stale.fail = [requests.exceptions.ConnectionError("reset")]
        n = len(self.log)
        with mock.patch.object(t, "_note_health") as noted, \
                eb.at(eb.P3, "mark"):
            self.assertEqual(float(t.ticker("AAPL")["lastPrice"]), 100.0)
        sent = self.log[n:]
        self.assertEqual([w is stale for w, *_ in sent], [True, False])
        self.assertEqual([kw["timeout"] for *_x, kw in sent],
                         [(4.0, 10.0), (4.0, 10.0)])
        noted.assert_not_called()

    def test_a_fresh_retry_that_fails_too_is_todays_one_failure(self):
        t = self._client()
        with eb.at(eb.P2, "account sync"):
            t.account()
        self._pool().fail = [requests.exceptions.ConnectionError("reset")]
        self.fail_next = [requests.exceptions.ConnectTimeout("no connect")]
        n = len(self.log)
        with mock.patch.object(t, "_note_health") as noted:
            with eb.at(eb.P2, "account sync"):
                with self.assertRaises(requests.exceptions.ConnectTimeout):
                    t.account()
        self.assertEqual(len(self.log) - n, 2)
        self.assertEqual(noted.call_count, 1)
        self.assertEqual(noted.call_args.args, ("account",))

    def test_a_5xx_retry_stays_on_the_pooled_connection(self):
        t = self._client()
        self.routes.insert(0, ("GET", "/aggregate-portfolio",
                               [(503, {}), (200, AGG)]))
        with eb.at(eb.P2, "account sync"):
            self.assertEqual(t.account(), AGG)
        pool = self._pool()
        self.assertEqual([w for w, *_ in self.log], [pool, pool])
        self.assertFalse(pool.closed)

    def test_a_session_idle_past_its_limit_is_replaced(self):
        t = self._client()
        clock = _Clock(1000.0)
        with mock.patch.object(ec, "_pool_mono", clock), \
                eb.at(eb.P2, "account sync"):
            t.account()
            first = self._pool()
            clock.t += ec.READ_POOL_IDLE_S - 1
            t.account()
            self.assertIs(self._pool(), first, "inside a burst: reused")
            clock.t += ec.READ_POOL_IDLE_S + 1
            t.account()
            self.assertIsNot(self._pool(), first,
                             "after a quiet beat: a fresh connection")
            self.assertTrue(first.closed)
        self.assertEqual([w is first for w, *_ in self.log],
                         [True, True, False])

    def test_a_forked_child_never_uses_its_parents_sockets(self):
        t = self._client()
        with eb.at(eb.P2, "account sync"):
            t.account()
        parent = self._pool()
        ec._pool_after_fork()
        self.assertEqual(ec._POOL, {})
        with eb.at(eb.P2, "account sync"):
            t.account()
        self.assertIsNot(self._pool(), parent)
        self.assertFalse(parent.closed, "a child never closes its parent's "
                                        "sockets")
        # and a session another process built is never reused
        child = self._pool()
        with mock.patch("os.getpid", return_value=os.getpid() + 1), \
                eb.at(eb.P2, "account sync"):
            t.account()
        self.assertIsNot(self.log[-1][0], child)
        self.assertFalse(child.closed)

    def test_a_tighter_client_timeout_caps_the_read_timeouts(self):
        """A pooled read is never given longer than the client asked: a mark
        on a client built at 5 s takes (4, 5), at 3 s (3, 3). Telegram
        /status builds its client at 5 s, and its account reads (P2) keep
        that 5 s, today's."""
        t = self._client(timeout=5.0)
        with eb.at(eb.P3, "mark"):
            t.ticker("AAPL")
        self.assertEqual({kw["timeout"] for *_x, kw in self.log},
                         {(4.0, 5.0)})
        with eb.at(eb.P2, "status read"):
            t.account()
        self.assertEqual(self.log[-1][3]["timeout"], 5.0)
        self.assertIn("aggregate-portfolio", self.log[-1][2])
        with eb.at(eb.P3, "mark"):
            self._client(timeout=3.0).ticker("AAPL")
        self.assertEqual(self.log[-1][3]["timeout"], (3.0, 3.0))

    def test_the_pooled_session_keeps_no_cookie(self):
        """The pool shares sockets and nothing else: no cookie one client
        was handed rides another's request."""
        import email.message
        import urllib.parse
        s = ec._new_read_session()
        host = urllib.parse.urlsplit(ec.BASE).hostname
        msg = email.message.Message()
        msg["Set-Cookie"] = f"__cf_bm=abc; Domain={host}; Path=/"

        class _Answer:
            def info(self):
                return msg
        req = urllib.request.Request(ec.BASE + "/api/v1/market-data/search")
        s.cookies.extract_cookies(_Answer(), req)
        self.assertEqual(list(s.cookies), [])
        jar = requests.cookies.RequestsCookieJar()
        jar.extract_cookies(_Answer(), req)
        self.assertEqual(len(list(jar)), 1, "the control keeps it")

    def test_a_supplied_session_carries_every_request_as_before(self):
        """A session handed to the client from outside (a shell's, a test's
        fake wire) carries every request, reads included, at today's
        timeout: the pool is for the client's own sessions only."""
        t = self._client()
        fake = _Wire(self.routes, self.log)
        t._session = fake
        with eb.at(eb.P3, "mark"):
            t.ticker("AAPL")
        self.assertTrue(self.log)
        self.assertTrue(all(w is fake for w, *_ in self.log))
        self.assertEqual({kw["timeout"] for *_x, kw in self.log}, {10.0})
        self.assertNotIn(KH, ec._POOL)
        other = self._client()
        n = len(self.log)
        with mock.patch.object(ec.EtoroTrader, "_sess", lambda self: fake), \
                eb.at(eb.P2, "account sync"):
            other.account()
        self.assertEqual([w for w, *_ in self.log[n:]], [fake])
        self.assertNotIn(KH, ec._POOL)

    def test_the_candles_of_a_pass_reuse_one_connection(self):
        """The bar refresh's burst — a candle a second — is where the
        handshakes were: one connection now serves the pass."""
        a, b = self._client(), self._client()
        a.klines("AAPL", "1h", 5)
        b.klines("MSFT", "1h", 5)
        pool = self._pool()
        self.assertEqual(len(self.log), 4)
        self.assertTrue(all(w is pool for w, *_ in self.log))


class ALiveSeriesThroughASlowConnectTests(bq._Base):
    """A connect that takes 6 s answered at today's 10 s. The candles keep
    the client's own timeout on the pool, so a live config's series stays
    eToro's own: no error, no public feed, no six-hour mute
    (bot_bars.MUTE_VENUE_MEMO_S). Under (4, 10) both reads failed, the
    public feed wrote the series and eToro was not asked for it again for
    six hours (2026-11-01, review)."""

    def setUp(self):
        super().setUp()
        self.feed = _RowsFeed()
        ec._POOL.clear()
        self.addCleanup(ec._POOL.clear)
        self.attempts = []
        for p in (mock.patch.object(ec, "READ_POOL", True),
                  mock.patch.object(
                      ec.requests, "Session",
                      side_effect=lambda: _SlowConnect(self.wire,
                                                       self.attempts)),
                  mock.patch("time.sleep")):
            p.start()
            self.addCleanup(p.stop)

    def _own(self, *_a, **_k):
        """The router's client: its transport is its own, so its candles
        ride the pool."""
        return ec.EtoroTrader("k", "u", env="live")

    def test_a_live_configs_series_stays_etoros(self):
        from django.core.cache import cache

        from market_data.models import PriceData
        self._cfg(["EURUSD"], mode="live", name="L")
        out = self._run(client_for=self._own)
        self.assertEqual(len(self.wire.candle_calls()), 2, self.attempts)
        self.assertEqual((out["errors"], out["fallback"]), (0, 0), out)
        self.assertEqual(self.feed.calls, [])
        self.assertEqual(set(PriceData.objects
                             .filter(instrument__symbol="EURUSD")
                             .values_list("source", flat=True)), {"etoro"})
        for interval in ("4h", "1h"):
            self.assertIsNone(cache.get(f"bars:mute:etoro:EURUSD:{interval}"),
                              interval)
        self.assertTrue(self.attempts)
        self.assertEqual({t for _m, _u, t in self.attempts}, {10.0})


class TheSyncThroughASlowConnectTests(TestCase):
    """The same 6 s connect on the account sync (P2): it keeps the client's
    own timeout on the pool, so it stores its reading, counts no missed
    pass (three are the stall alert; an hour without cells refuses every
    eToro order) and notes nothing on the venue's health. Only the manage
    tick's own reads (P3, P4) take the 4 s connect, and pay it (2026-11-01,
    review)."""

    def setUp(self):
        from django.core.cache import cache

        from bot_program import venue_health
        from tests.test_sync_walks_etoro import _etoro
        cache.clear()
        venue_health.reset()
        self.addCleanup(venue_health.reset)
        self.addCleanup(cache.clear)
        for memo in (ec._SEARCH_IDS, ec._SEARCH_NO):
            memo.clear()
            self.addCleanup(memo.clear)
        ec._POOL.clear()
        self.addCleanup(ec._POOL.clear)
        self.user = User.objects.create_user("e3_slow", password="x")
        self.acct = _etoro(self.user, demo=False, is_primary_for_stocks=True)
        self.log, self.attempts = [], []
        inner = _Wire(_routes(), self.log)
        for p in (mock.patch.object(ec, "READ_POOL", True),
                  mock.patch.object(
                      ec.requests, "Session",
                      side_effect=lambda: _SlowConnect(inner, self.attempts)),
                  mock.patch("time.sleep")):
            p.start()
            self.addCleanup(p.stop)

    def _notes(self):
        from bot_program import venue_health
        return (venue_health._load(venue_health._key("etoro", "live"))
                .get("failures") or [])

    def test_the_sync_stores_its_reading_and_counts_no_miss(self):
        from django.core.cache import cache

        from bot_program.models import EtoroAccount
        from bot_program.tasks import sync_etoro_accounts
        with mock.patch("bot_program.notifications.notify_staff"):
            out = sync_etoro_accounts.__wrapped__.__wrapped__()
        self.assertEqual((out["attempted"], out["stored"],
                          out["unreachable"]), (1, 1, 0), out)
        self.assertIsNone(cache.get(f"broker_sync:miss:etoro:{self.acct.pk}"))
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertIsNotNone(acct.last_equity_at)
        self.assertIsNotNone(acct.last_margin_at)
        self.assertEqual(self._notes(), [], "nothing noted on its health")
        self.assertTrue(self.attempts)
        self.assertEqual({t for _m, _u, t in self.attempts}, {10.0})

    def test_the_ticks_mark_pays_the_short_connect_as_stated(self):
        """The control, the cost the commit states: a mark of a row whose
        stop rests at eToro (P3) gives way after its one retry at (4, 10),
        about 9 s, with ONE note on the venue's health (three inside 180 s
        make eToro sick and hold new real entries); the row is only
        clock-managed for that tick."""
        t = ec.EtoroTrader("api-k", USER_KEY, env="live")
        with eb.at(eb.P3, "mark"):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                t.ticker("AAPL")
        self.assertEqual([tm for _m, _u, tm in self.attempts],
                         [(4.0, 10.0)] * 2)
        self.assertEqual(len(self._notes()), 1, self._notes())


# ── the pool check from the sync ──────────────────────────────────────────

class ThePoolCheckReadsTheSyncsEquityTests(TestCase):
    """capital_truth.broker_equity (the pool check in can_open_new, and the
    mismatch pages) reads the account's equity as the sync stored it, at
    today's 15-minute freshness; it no longer sends one aggregate GET per
    live config."""

    def setUp(self):
        from bot_program.models import AssetBotConfig, EtoroAccount
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        self.user = User.objects.create_user("e3_pc", password="x")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="pc", mode="live",
            symbols=["AAPL"], capital=Decimal("100000"), enabled=True)
        self.acct = EtoroAccount.objects.create(user=self.user, demo=False)
        self.acct.set_credentials("api-k", USER_KEY)
        self.acct.save()

    def _stored(self, value="20000", *, age_s=120, world="live"):
        self.acct.last_equity = (None if value is None
                                 else Decimal(str(value)))
        self.acct.last_equity_currency = "USD"
        self.acct.last_equity_at = timezone.now() - timedelta(seconds=age_s)
        self.acct.last_margin_world = world
        self.acct.last_margin_at = self.acct.last_equity_at
        self.acct.save()

    def _equity(self, env="live", cfg=None):
        from bot_program import capital_truth
        wire = _Wire(_routes(), [])
        t = ec.EtoroTrader("api-k", USER_KEY, env=env)
        t._session = wire
        with mock.patch(ROUTER, return_value=t):
            got = capital_truth.broker_equity(self.user, cfg or self.cfg)
        return got, wire

    def _forget_said(self):
        """The pool check's memory of what it said at INFO is per process:
        a user id an earlier test used would otherwise be remembered."""
        from bot_program import capital_truth
        capital_truth._SAID.clear()
        self.addCleanup(capital_truth._SAID.clear)

    def test_the_stored_equity_is_read_and_nothing_is_sent(self):
        self._stored("20000", age_s=120)
        got, wire = self._equity()
        self.assertEqual(got, 20000.0)
        self.assertEqual(wire.log, [])
        self.cfg.refresh_from_db()
        self.assertNotIn("broker_equity", self.cfg.extras or {},
                         "a stored reading is not cached a second time")

    def test_an_equity_past_fifteen_minutes_is_not_measured(self):
        self._stored("20000", age_s=15 * 60 + 5)
        got, wire = self._equity()
        self.assertIsNone(got)
        self.assertEqual(wire.log, [])

    def test_an_equity_just_inside_fifteen_minutes_still_stands(self):
        self._stored("20000", age_s=15 * 60 - 5)
        self.assertEqual(self._equity()[0], 20000.0)

    def test_an_equity_never_stored_is_not_measured(self):
        self._stored(None)
        got, wire = self._equity()
        self.assertIsNone(got)
        self.assertEqual(wire.log, [])

    def test_an_equity_read_in_the_other_world_is_not_measured(self):
        self._stored("20000", world="demo")
        self.assertIsNone(self._equity()[0])
        self._stored("20000", world="")
        self.assertIsNone(self._equity()[0])

    def test_a_demo_row_reads_its_demo_equity(self):
        self.acct.demo = True
        self.acct.save(update_fields=["demo"])
        self._stored("50000", world="demo")
        self.assertEqual(self._equity(env="demo")[0], 50000.0)

    def test_a_zero_is_not_measured(self):
        self._stored("0")
        self.assertIsNone(self._equity()[0])

    def test_its_age_is_stated(self):
        self._stored("20000", age_s=200)
        with self.assertLogs("bot_program.capital_truth", level="DEBUG") as lg:
            self._equity()
        self.assertTrue(any("as the sync stored it" in ln
                            and "old" in ln for ln in lg.output), lg.output)
        self._stored("20000", age_s=20 * 60)
        with self.assertLogs("bot_program.capital_truth", level="DEBUG") as lg:
            self._equity()
        self.assertTrue(any("not measured" in ln and "min old" in ln
                            for ln in lg.output), lg.output)

    def test_its_age_is_said_at_the_level_production_writes(self):
        """Production writes bot_program at INFO (core/logging_config, DEBUG
        off): the reading with its age, and why none stands, are said at
        INFO there. A DEBUG line alone was never written in production
        (2026-11-01, review)."""
        from core.logging_config import build_logging_config
        prod = build_logging_config(debug=False)["loggers"]["bot_program"]
        self.assertEqual(prod["level"], "INFO")
        self._forget_said()
        self._stored("20000", age_s=200)
        with self.assertLogs("bot_program.capital_truth", level="INFO") as lg:
            self.assertEqual(self._equity()[0], 20000.0)
        self.assertTrue(any(ln.startswith("INFO:")
                            and "as the sync stored it, 200 s old" in ln
                            for ln in lg.output), lg.output)
        self._stored("20000", age_s=20 * 60)
        with self.assertLogs("bot_program.capital_truth", level="INFO") as lg:
            self.assertIsNone(self._equity()[0])
        self.assertTrue(any(ln.startswith("INFO:") and "not measured" in ln
                            and "20.0 min old (limit 15 min)" in ln
                            for ln in lg.output), lg.output)

    def test_it_is_said_once_per_user_reason_and_fifteen_minutes(self):
        """can_open_new asks for every live config every tick: a user's
        reason is said at INFO the first time it comes up in CACHE_SECONDS,
        at DEBUG in between (another config of the same account included),
        and at INFO again on another reason or past the window."""
        from bot_program import capital_truth
        from bot_program.models import AssetBotConfig
        self._forget_said()
        other = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="pc2", mode="live",
            symbols=["AAPL"], capital=Decimal("50000"), enabled=True)
        clock = _Clock(1000.0)

        def levels(cfg=None):
            with self.assertLogs("bot_program.capital_truth",
                                 level="DEBUG") as lg:
                self._equity(cfg=cfg)
            return [r.levelname for r in lg.records
                    if "pool check" in r.getMessage()]
        with mock.patch.object(capital_truth, "_said_mono", clock):
            self._stored("20000", age_s=200)
            self.assertEqual(levels(), ["INFO"])
            clock.t += 60
            self.assertEqual(levels(), ["DEBUG"])
            self.assertEqual(levels(other), ["DEBUG"], "one account, one line")
            self._stored("20000", age_s=20 * 60)
            self.assertEqual(levels(), ["INFO"], "another reason, at once")
            self.assertEqual(levels(), ["DEBUG"])
            self._stored("20000", age_s=200)
            clock.t += capital_truth.CACHE_SECONDS - 61
            self.assertEqual(levels(), ["DEBUG"], "inside its window")
            clock.t += 1
            self.assertEqual(levels(), ["INFO"], "past its window")

    def test_the_mismatch_is_judged_on_the_stored_equity(self):
        from bot_program import capital_truth
        self._stored("20000")
        wire = _Wire(_routes(), [])
        t = ec.EtoroTrader("api-k", USER_KEY, env="live")
        t._session = wire
        with mock.patch(ROUTER, return_value=t):
            rows = capital_truth.capital_mismatches(self.user)
        self.assertEqual([(r["direction"], r["ratio"]) for r in rows],
                         [("over", 5.0)])
        self.assertEqual(wire.log, [])

    def test_another_venue_still_asks_its_own_adapter(self):
        """Saxo and IBKR keep their own read: only eToro's sync stores
        the equity this check reads."""
        from bot_program import capital_truth
        other = mock.MagicMock(spec=["net_liquidation"])
        other.net_liquidation.return_value = (20000.0, "USD")
        with mock.patch(ROUTER, return_value=other):
            self.assertEqual(capital_truth.broker_equity(self.user, self.cfg),
                             20000.0)
        other.net_liquidation.assert_called_once()


# ── the beats ─────────────────────────────────────────────────────────────

class TheBeatsAreOffsetTests(SimpleTestCase):
    """The eToro sync and the reconcile no longer fire with the five-minute
    marks: the sync at minute 1 of every five, the reconcile at minute 3,
    pinned to the clock; the bot tick keeps its 300 s interval."""

    def _beat(self, key):
        from config.celery import app
        return app.conf.beat_schedule[key]["schedule"]

    def test_the_tick_is_the_300_s_interval_it_was(self):
        self.assertEqual(self._beat("tick-asset-bots"), 300.0)

    def test_the_sync_fires_at_minute_one_of_every_five(self):
        from celery.schedules import crontab
        sync = self._beat("sync-etoro-accounts")
        self.assertIsInstance(sync, crontab)
        self.assertEqual(sorted(sync.minute), list(range(1, 60, 5)))
        self.assertEqual(len(sync.hour), 24)
        self.assertEqual(len(sync.day_of_week), 7)

    def test_the_reconcile_fires_at_minute_three_of_every_five(self):
        from celery.schedules import crontab
        rec = self._beat("reconcile-asset-bot-trades")
        self.assertIsInstance(rec, crontab)
        self.assertEqual(sorted(rec.minute), list(range(3, 60, 5)))
        self.assertEqual(len(rec.hour), 24)

    def test_neither_fires_on_a_five_minute_mark_nor_beside_the_other(self):
        sync = set(self._beat("sync-etoro-accounts").minute)
        rec = set(self._beat("reconcile-asset-bot-trades").minute)
        self.assertFalse({m for m in sync | rec if m % 5 == 0})
        self.assertEqual(sync & rec, set())

    def test_both_still_beat_every_five_minutes(self):
        from core.component_digest import _period_hours
        from core.day_of_sauron import schedule_words
        for key in ("sync-etoro-accounts", "reconcile-asset-bot-trades"):
            words, period, kind, _first = schedule_words(self._beat(key))
            self.assertEqual((words, period, kind),
                             ("every 5 min", 300.0, "cron"), key)
            self.assertAlmostEqual(_period_hours(self._beat(key)),
                                   300 / 3600, msg=key)


class TheSchedulerKeepsTheOffsetsTests(TestCase):
    """The beat runs django_celery_beat's DatabaseScheduler: the minutes
    survive its conversion into a stored crontab."""

    def test_the_database_scheduler_keeps_both_minutes(self):
        from django_celery_beat.schedulers import ModelEntry

        from config.celery import app
        for key, first in (("sync-etoro-accounts", 1),
                           ("reconcile-asset-bot-trades", 3)):
            model, field = ModelEntry.to_model_schedule(
                app.conf.beat_schedule[key]["schedule"])
            self.assertEqual(field, "crontab", key)
            self.assertEqual(model.minute, f"{first}-59/5", key)


# ── one book per reconcile pass ───────────────────────────────────────────

class OneBookPerPassTests(TestCase):
    """reconcile_all_users reads eToro's book ONCE per user and world for
    the row walk and the unclaimed sweep (two GETs of /portfolio before);
    each reader names the rows with its own warm, and the sweep's grace
    runs from the instant that book was read."""

    def setUp(self):
        from tests.test_reconcile_by_id import _cfg, _trade
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        self.user = User.objects.create_user("e3_rc", password="x")
        self.cfg = _cfg(self.user, asset_class="stock", name="st")
        self.cfg.symbols = ["AAPL", "MSFT"]
        self.cfg.save(update_fields=["symbols"])
        self._trade = _trade
        self.row = _trade(self.cfg, symbol="AAPL", pid="999")
        self.routes, self.log = _routes(), []
        self.wire = _Wire(self.routes, self.log)

    def _make(self, *_a, **_k):
        t = ec.EtoroTrader("api-k", USER_KEY, env="live")
        t._session = self.wire
        return t

    def _books(self):
        return [c for c in self.log if "/info/portfolio" in c[2]]

    def _all_users(self):
        from bot_program import reconcile_asset
        with mock.patch(ROUTER, side_effect=self._make), \
                mock.patch("time.sleep"), \
                mock.patch("bot_program.notifications."
                           "notify_unclaimed_position") as told:
            totals = reconcile_asset.reconcile_all_users()
        return totals, told

    def test_one_pass_reads_the_book_once_for_the_walk_and_the_sweep(self):
        totals, told = self._all_users()
        self.assertEqual(len(self._books()), 1, self.log)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "OPEN")
        # the sweep named the book with its own warm (the config's two
        # symbols): MSFT is unclaimed by name, never "unnamed"
        self.assertEqual(totals["unclaimed"], 1, totals)
        told.assert_called_once()
        self.assertEqual(told.call_args.kwargs["symbols"], ["MSFT"])

    def test_a_failed_book_is_asked_again_by_the_next_reader(self):
        # 2026-11-02 (completes E3, review): was ..._is_the_passs_answer_
        # and_never_asked_twice (one read and its retry for both walks: one
        # failure toward SICK where there were two). A FAILED read is not
        # shared: the sweep asks again, as each reader did before the pass
        # shared its book, and a second failure is noted
        from bot_program import venue_health as vh
        vh.reset()
        self.addCleanup(vh.reset)
        self.routes.insert(0, ("GET", "/info/portfolio", [(503, {})]))
        totals, told = self._all_users()
        self.assertEqual(len(self._books()), 2 * (1 + ec.READ_RETRIES),
                         "each reader's read and its one retry")
        self.assertEqual(len(vh._load(vh._key("etoro", "live"))["failures"]),
                         2)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "OPEN")
        self.assertGreaterEqual(totals["broker_unavailable"], 2, totals)
        told.assert_not_called()

    def test_a_book_the_budget_did_not_send_is_the_passs_answer(self):
        # the control: a refusal is no failure, nothing was sent, and the
        # sweep is not asked again (its words are the walk's)
        from tests.test_etoro_budget import _fill
        eb.reset()
        self.addCleanup(eb.reset)
        with mock.patch.object(eb, "BUDGET", True):
            _fill(eb.key_hash(USER_KEY), eb.ACCOUNT,
                  eb.limit(eb.ACCOUNT, eb.P2))
            totals, told = self._all_users()
        self.assertEqual(self._books(), [], "nothing sent")
        self.assertGreaterEqual(totals["broker_unavailable"], 2, totals)
        told.assert_not_called()

    def test_outside_a_pass_each_reader_reads_its_own_book(self):
        from bot_program import reconcile_asset
        with mock.patch(ROUTER, side_effect=self._make), \
                mock.patch("time.sleep"), \
                mock.patch("bot_program.notifications."
                           "notify_unclaimed_position"):
            reconcile_asset.reconcile_user(self.user)
            reconcile_asset.reconcile_unknown_positions(self.user)
        self.assertEqual(len(self._books()), 2)

    def _swept_with_a_book_read(self, seconds_ago):
        from bot_program import reconcile_asset as ra
        closed = self._trade(self.cfg, symbol="MSFT", pid="1000")
        closed.status = "CLOSED"
        closed.closed_at = timezone.now() - timedelta(seconds=130)
        closed.save(update_fields=["status", "closed_at"])
        with ra.one_book_per_pass():
            ra._BOOKS.get()[(KH, "live")] = {
                "rows": BOOK["positions"],
                "at": timezone.now() - timedelta(seconds=seconds_ago)}
            with mock.patch(ROUTER, side_effect=self._make), \
                    mock.patch("bot_program.notifications."
                               "notify_unclaimed_position"):
                out = ra.reconcile_unknown_positions(self.user)
        self.assertEqual(self._books(), [], "the pass's book, never a second")
        return out

    def test_the_sweeps_grace_runs_from_the_books_read(self):
        """The book read 100 s ago still lists MSFT, closed 30 s before
        that read (eToro lists a closed position up to 60 s): the row
        closed within the grace of THE READ still claims its symbol."""
        out = self._swept_with_a_book_read(100)
        self.assertEqual(out["unclaimed"], 0, out)

    def test_the_grace_is_the_reads_not_a_wider_one(self):
        """The control: the same row against a book read now is 130 s past
        the read, outside the 120 s grace, and is reported."""
        out = self._swept_with_a_book_read(0)
        self.assertEqual(out["symbols"], ["MSFT"], out)

    def test_the_row_walk_keeps_its_lag_window(self):
        """A row filled 30 s ago is absent from the shared book (eToro lists
        a fill ~2 s late, settled by 60 s): never orphan-closed."""
        self.routes.insert(0, ("GET", "/info/portfolio", [(200, {
            "positions": [BOOK["positions"][0]]})]))
        young = self._trade(self.cfg, symbol="MSFT", pid="")
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=young.pk).update(
            opened_at=timezone.now() - timedelta(seconds=30))
        with self.assertLogs("bot_program.reconcile_asset",
                             level="WARNING") as lg:
            self._all_users()
        young.refresh_from_db()
        self.assertEqual(young.status, "OPEN")
        self.assertTrue(any("position list lags up to 60 s" in ln
                            for ln in lg.output), lg.output)
        self.assertEqual(len(self._books()), 1)


# ── the zero gaps ─────────────────────────────────────────────────────────

class TheLegacyLaneNeverClosesALiveRowOnNoPriceTests(TestCase):
    """bot_program/engine/runner.py, reached by the "Run tick now" button:
    a LIVE row at a price of 0, below it or unreadable is not managed this
    tick — no stop, target or close is judged on it, nothing is sent, and
    the log says why. A live BUY at "0" read as its stop hit and a SELL as
    its target, and a market close went out."""

    def _row(self, side="BUY", paper=False):
        from bot_program.models import BotConfig, BotTrade
        user = User.objects.create_user(f"e3_lg_{side}_{paper}_"
                                        f"{BotTrade.objects.count()}",
                                        password="x")
        cfg = BotConfig.objects.create(
            user=user, capital_usdt=Decimal("1000"), enabled=True,
            mode="paper" if paper else "live", symbols=[])
        buy = side == "BUY"
        return BotTrade.objects.create(
            config=cfg, symbol="BTCUSDT", side=side, qty=Decimal("1"),
            entry_price=Decimal("100"),
            stop_loss=Decimal("95") if buy else Decimal("105"),
            take_profit=Decimal("110") if buy else Decimal("90"),
            paper=paper, status="OPEN")

    def _tick(self, trade, price, *, logs=True):
        import contextlib

        from bot_program.engine import runner
        from tests.test_legacy_close import _client
        client = _client()
        client.ticker.return_value = ({} if price is ... else
                                      {"lastPrice": price})
        watch = (self.assertLogs("bot_program.engine.runner", level="INFO")
                 if logs else contextlib.nullcontext())
        with mock.patch.object(runner, "client_for_symbol",
                               return_value=client), watch as lg:
            runner.run_bot_tick(trade.config.user_id)
        return client, (lg.output if logs else [])

    def _left_alone(self, trade, price, words):
        client, out = self._tick(trade, price)
        client.market_order.assert_not_called()
        client.close_position.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        said = [ln for ln in out if ln.startswith("WARNING")
                and f"#{trade.id}" in ln]
        self.assertEqual(len(said), 1, out)
        self.assertIn("not managed this tick", said[0])
        self.assertIn("nothing is sent", said[0])
        self.assertIn(words, said[0])

    def test_a_live_buy_at_zero_is_not_a_stop_hit(self):
        self._left_alone(self._row("BUY"), "0", "lastPrice '0'")

    def test_a_live_sell_at_zero_is_not_a_target_hit(self):
        self._left_alone(self._row("SELL"), "0", "lastPrice '0'")

    def test_a_live_row_below_zero_is_left_alone(self):
        self._left_alone(self._row("BUY"), "-1", "lastPrice '-1'")

    def test_an_unreadable_live_price_is_left_alone(self):
        for price, words in (("abc", "lastPrice 'abc'"),
                             ("NaN", "lastPrice 'NaN'"),
                             ("Infinity", "lastPrice 'Infinity'"),
                             (None, "lastPrice None"),
                             (..., "lastPrice None")):
            with self.subTest(price=price):
                self._left_alone(self._row("SELL"), price, words)

    def test_a_live_row_at_a_real_price_still_closes_on_its_stop(self):
        """The control: the guard refuses no price."""
        trade = self._row("BUY")
        client, _out = self._tick(trade, "90", logs=False)
        client.market_order.assert_called_once()

    def test_a_paper_row_keeps_its_own_check(self):
        trade = self._row("BUY", paper=True)
        with mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                        return_value=""):
            client, out = self._tick(trade, "0")
        client.market_order.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(any("legacy paper" in ln and "no usable price" in ln
                            for ln in out), out)
        self.assertFalse([ln for ln in out if "not managed this tick" in ln])


class TheTreasuryPrintsADashForAnUnreadMarkTests(TestCase):
    """manage.py treasury printed "mark 0.0000" for every eToro holding:
    eToro's /portfolio rows carry no mark (broker_portfolio leaves
    market_price 0.0), and a 0 is never a price."""

    HELD = {"symbol": "GLDM", "side": "BUY", "qty": 1.0, "avg_cost": 84.8,
            "market_price": 0.0, "market_value": 0.0, "unrealized_pnl": 0.0,
            "currency": "", "sec_type": "CFD"}

    def _line(self, held):
        from tests.test_treasury import an_etoro
        user = User.objects.create_user(f"e3_tr_{len(held)}_"
                                        f"{User.objects.count()}",
                                        password="x")
        an_etoro(user, held=held)
        out = StringIO()
        call_command("treasury", user=user.username, stdout=out)
        body = out.getvalue()
        return body, [ln for ln in body.splitlines() if " @ " in ln]

    def test_an_unread_etoro_mark_prints_the_dash(self):
        body, lines = self._line([self.HELD])
        self.assertNotIn("mark       0.0000", body)
        self.assertEqual(len(lines), 1, body)
        self.assertIn(f"mark {'—':>12}  ", lines[0])
        self.assertIn("84.8000", lines[0], "the cost is still printed")

    def test_a_missing_or_negative_mark_prints_the_dash_too(self):
        held = [dict(self.HELD, market_price=None),
                dict(self.HELD, symbol="HYG", market_price=-1.0),
                dict(self.HELD, symbol="SLV", market_price="nan")]
        _body, lines = self._line(held)
        self.assertEqual(len(lines), 3)
        for ln in lines:
            self.assertIn(f"mark {'—':>12}  ", ln)

    def test_a_read_mark_still_prints_its_price(self):
        _body, lines = self._line([dict(self.HELD, market_price=85.25)])
        self.assertIn(f"mark {85.25:>12.4f}  ", lines[0])


class TheSmokeIsPacedTests(TestCase):
    """etoro_smoke sends one request a second, its retries included, every
    one at P5: it ran unpaced, a burst of a dozen reads or more in a second
    on the operator's own key beside the tick's marks."""

    def test_every_request_is_a_second_apart_and_at_p5(self):
        from bot_program.management.commands import etoro_smoke
        from tests.test_etoro_smoke import (ROUTES, _FakeSession, _keyed,
                                            _live_cfg)
        user = User.objects.create_user("e3_smoke", password="x")
        _keyed(user)
        _live_cfg(user, "commodity_etf", ["GLDM", "HYG"])
        clock = _Clock(5000.0)

        def sleep(seconds):
            clock.t += float(seconds)
        stamps = []
        fake = _FakeSession(list(ROUTES))
        hit = fake._hit

        def stamped(method, url, **kw):
            stamps.append((clock.t, eb.current(eb.P1)[0], url))
            return hit(method, url, **kw)
        fake._hit = stamped
        with mock.patch.object(etoro_smoke, "SMOKE_GAP_S", 1.0), \
                mock.patch.object(etoro_smoke, "_mono", clock), \
                mock.patch.object(etoro_smoke, "_sleep", sleep), \
                mock.patch("time.sleep", sleep), \
                mock.patch.object(ec.EtoroTrader, "_sess",
                                  lambda self: fake):
            call_command("etoro_smoke", user="e3_smoke", stdout=StringIO(),
                         symbol=["BOOM"], other_world=True)
        self.assertGreaterEqual(len(stamps), 10)
        gaps = [b[0] - a[0] for a, b in zip(stamps, stamps[1:])]
        self.assertGreaterEqual(min(gaps), 1.0 - 1e-9, list(zip(gaps, stamps)))
        self.assertEqual({p for _t, p, _u in stamps}, {eb.P5})
        # the 503 on BOOM's /search was asked once more, a second later
        boom = [t for t, _p, u in stamps if "search" in u][-2:]
        self.assertEqual(len(boom), 2)
        self.assertGreaterEqual(boom[1] - boom[0], 1.0 - 1e-9)

    def test_the_suite_runs_the_smoke_unpaced(self):
        from bot_program.management.commands import etoro_smoke
        self.assertEqual(etoro_smoke.SMOKE_GAP_S, 0.0)
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_smoke.SMOKE_GAP_S = 0.0", src)
