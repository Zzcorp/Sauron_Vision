"""THE SHORTS THE PLATFORM PROVES ITSELF ON THE DEMO ACCOUNT (2026-10-31).

The operator, 2026-10-31: "je veux les short possible entierement svp" (I
want shorts fully possible, please). The TAKE TRADE lane shorts every class
eToro allows since S1; the BOTS short a class only once its short is
proven. Until now a proof was a developer's sitting, pinned by hand in
tests/test_etoro_client.py (base.ETORO_SHORT_PROVEN: stock and forex). Now
the platform measures the others itself (bot_program/short_proofs.py):

  * ONLY ON eToro's DEMO SEGMENT, whatever the eToro row's live/demo flag
    says: one key pair opens both worlds (measured 2026-09-23) and the URL
    segment alone picks the world, so the runner's client
    (etoro_client.DemoOnlyEtoroTrader) writes the demo segment by
    construction and refuses, before the wire, any URL that is not on it.
  * One class at a time, spaced out, only while that instrument's market is
    open on the platform's own clock, never while eToro is sick, after a
    429, or while a real close is pending (closes first): it reads eToro's
    short eligibility, sells the venue minimum, reads the fill, closes it,
    reads the close, and records the round trip as a demo proof
    (EtoroShortObservation, demo_proven).
  * A POST that did not come back is IN DOUBT: nothing is sent again, the
    runner stops, and the alarm rings, until a superuser clears it.
  * THE BOTS' GATE reads a code-pinned proof OR a recorded demo proof for
    (class, side, leverage): a class the runner proved opens to the bots at
    the measured multiplier only. The operator hears it on Telegram, and a
    superuser can revoke a proof on /short-proofs/ with the trading PIN.
  * Once per class, an overnight hold measures the short's overnight fee;
    the cost model then charges the measured short fee, never less than
    the fee it charged before.
  * Behind the component switch short_proofs_demo, ON by default (it only
    ever touches the demo account), on the beat and as a command with
    --dry-run.

The eToro client is the REAL adapter over a fake wire (_Wire below), so
every URL the runner sends is the one the adapter composes.

Run with:  python manage.py test tests.test_short_proofs
"""
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import requests
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from requests.adapters import BaseAdapter
from requests.models import Response

from tests.test_etoro_client import _Resp, _clear_eligibility, _elig_row, _lev
from tests.test_manual_shorts import _short_lookup

User = get_user_model()
UTC = dt_timezone.utc

NOTIFY = "bot_program.notifications.notify_staff"
ALARM = "bot_program.alarm.send_alarm"
SHORTS = "bot_program.asset_engine.base.ETORO_SHORT_PROVEN"
PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"
TITLE = ("Short on {cls} proven on the demo account: the bots may now short "
         "it at {lev}x")

#: Sunday 1 November 2026, noon UTC: crypto trades, every other market
#: Sauron models is shut.
SUNDAY = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
#: Monday 2 November 2026, 16:00 UTC (11:00 New York, DST over): New York
#: and CME are open and settled.
MONDAY = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

# Demo eligibility rows, in the shapes measured on 2026-09-23 (tests/
# test_etoro_client.py), with the short entries the LIVE rows print.
ROW_BTC = _elig_row(100000, "BTC", [
    _lev("real", "long", [1], max_sl=100),
    _lev("cfd", "long", [2]),
    _lev("cfd", "short", [1, 2])], max_units=41, w8=False)
ROW_GLDM = _elig_row(3190, "GLDM", [
    _lev("cfd", "long", [1], max_sl=100),
    _lev("cfd", "long", [2, 5]),
    _lev("cfd", "short", [1, 2, 5])], units="whole")
ROW_SPX = _elig_row(27, "SPX500", [
    _lev("cfd", "long", [1], max_sl=100, min_amount=50),
    _lev("cfd", "short", [1, 2, 5], min_amount=50)],
    min_exposure=1000, w8=False, units="whole")
ROW_NSDQ = _elig_row(28, "NSDQ100", [
    _lev("cfd", "long", [1], max_sl=100, min_amount=50),
    _lev("cfd", "short", [1, 2, 5], min_amount=50)],
    min_exposure=1000, w8=False, units="whole")
ROW_GOLD = _elig_row(18, "GOLD", [
    _lev("cfd", "long", [1], max_sl=100, min_amount=25),
    _lev("cfd", "short", [1, 2, 5], min_amount=25)],
    min_exposure=1000, w8=False, units="whole")
#: A row eToro prints with no short entry at all.
ROW_GLDM_NO_SHORT = _elig_row(3190, "GLDM", [
    _lev("cfd", "long", [1], max_sl=100)], units="whole")

SEARCH = {"BTC": 100000, "GLDM": 3190, "SPX500": 27, "NSDQ100": 28}
RATES = {100000: 60000.0, 3190: 80.0, 27: 6000.0, 28: 21000.0, 18: 4000.0}


class _Wire:
    """A fake eToro answering by what is asked: /search by spelling, the
    rates and the eligibility by instrument id, orders:lookup by order id
    (a list consumed in order, the last one repeats), the order POST with
    the next order id, the close POST, the DELETE and /portfolio. Records
    every call; `raise_on` (method, substring) raises instead."""

    def __init__(self, *, rows=None, lookups=None, accept=None, close=None,
                 portfolio=None, raise_on=None, order_status=None):
        self.headers = {}
        self.calls = []
        self.rows = {r["instrumentId"]: r for r in (rows or [])}
        self.lookups = {str(k): list(v) for k, v in (lookups or {}).items()}
        self.accept = list(accept or [7001])
        self.close = close
        self.portfolio = list(portfolio or [])
        self.raise_on = dict(raise_on or {})
        self.order_status = order_status

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for (m, sub), exc in self.raise_on.items():
            if m == method and sub in url:
                raise exc
        params = kw.get("params") or {}
        if "/market-data/search" in url:
            spelled = params.get("internalSymbolFull")
            iid = SEARCH.get(spelled)
            return _Resp(200, [{"instrumentId": iid,
                                "internalSymbolFull": spelled}]
                         if iid else [])
        if "/instruments/rates" in url:
            px = RATES.get(int(params.get("instrumentIds")))
            return _Resp(200, {"rates": [{"bid": px, "ask": px,
                                          "lastExecution": px}]})
        if "/eligibility" in url:
            ids = (kw.get("json") or {}).get("instrumentIds") or []
            return _Resp(200, {"currency": "usd", "eligibilities": [
                self.rows[i] for i in ids if i in self.rows]})
        if "orders:lookup" in url:
            seq = self.lookups.get(str(params.get("orderId") or ""))
            if not seq:
                return _Resp(404, {"message": "not found"})
            return _Resp(*(seq.pop(0) if len(seq) > 1 else seq[0]))
        if method == "POST" and url.endswith("/orders"):
            if self.order_status is not None:
                return _Resp(self.order_status, {"message": "refused"})
            oid = self.accept.pop(0) if len(self.accept) > 1 \
                else self.accept[0]
            return _Resp(200, {"token": "tok", "orderId": oid,
                               "referenceId": "ref"})
        if method == "DELETE" and "/orders/" in url:
            return _Resp(202, {"orderId": url.rsplit("/", 1)[-1],
                               "referenceId": ""})
        if "market-close-orders/positions/" in url:
            pid = int(url.rsplit("/", 1)[-1])
            return _Resp(*(self.close or (200, {
                "orderForClose": {"orderID": 8001, "positionID": pid,
                                  "orderType": 19, "statusID": 1, "CID": 9},
                "token": "tok"})))
        if "/portfolio" in url:
            return _Resp(200, {"clientPortfolio": {
                "positions": list(self.portfolio)}})
        return _Resp(404, {})

    def get(self, url, **kw):
        return self._hit("GET", url, **kw)

    def post(self, url, **kw):
        return self._hit("POST", url, **kw)

    def patch(self, url, **kw):
        return self._hit("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._hit("DELETE", url, **kw)

    def urls(self, method=None):
        return [u for m, u, _k in self.calls if method in (None, m)]


class _UnreadBody(_Resp):
    """A 2xx whose body is not JSON (an empty 202, an HTML page): json()
    raises as requests does (JSONDecodeError, a ValueError)."""

    def __init__(self, status=202, text="<html>accepted</html>"):
        super().__init__(status, {}, text=text)

    def json(self):
        raise requests.exceptions.JSONDecodeError("Expecting value",
                                                  self.text, 0)


class _UnreadAcceptance(_Wire):
    """eToro accepts the order POST with a body nobody can read."""

    def _hit(self, method, url, **kw):
        if method == "POST" and url.endswith("/orders"):
            self.calls.append((method, url, kw))
            return _UnreadBody()
        return super()._hit(method, url, **kw)


class _Transport(BaseAdapter):
    """eToro behind a REAL requests.Session (the review of 2026-10-31):
    every request the session sends is answered by `wire` (a _Wire),
    except a (method, path suffix) in `redirect`, answered with that 3xx
    and its Location (none when ""). Records every request that reached
    the transport, so a redirect requests followed shows as a second
    request. Nothing leaves the box."""

    def __init__(self, wire, redirect=None):
        super().__init__()
        self.wire = wire
        self.redirect = dict(redirect or {})
        self.sent = []

    def send(self, request, **kw):
        parts = urlsplit(request.url)
        self.sent.append((request.method, request.url))
        r = Response()
        r.request, r.url = request, request.url
        for (method, suffix), (code, location) in self.redirect.items():
            if request.method == method and parts.path.endswith(suffix):
                r.status_code = code
                if location:
                    r.headers["Location"] = location
                r._content = b""
                return r
        got = self.wire._hit(request.method,
                             urlunsplit(parts._replace(query="")),
                             params=dict(parse_qsl(parts.query)),
                             json=(json.loads(request.body)
                                   if request.body else None))
        r.status_code = got.status_code
        r.headers["Content-Type"] = "application/json"
        r._content = json.dumps(got._payload).encode()
        return r

    def close(self):
        pass


def _round_trip(order=7001, position=900001, *, symbol="BTC", iid=100000,
                units=0.0002, avg=60000.0, leverage=1, fees=0.0, **kw):
    """orders:lookup of a filled demo SELL: open at the fill, then closed."""
    body = dict(order=order, position=position, units=units, avg=avg,
                symbol=symbol, iid=iid, leverage=leverage, fees=fees, **kw)
    return [(200, _short_lookup(state="open", **body)),
            (200, _short_lookup(state="closed", **body))]


def _demo(wire):
    from bot_program.engine.etoro_client import DemoOnlyEtoroTrader
    t = DemoOnlyEtoroTrader("api-k", "user-k")
    t._session = wire
    return t


def _demo_over(transport):
    """The runner's client on its OWN requests.Session, as the runner
    builds it (the keys in its headers; the redirect machinery is
    requests'), with `transport` mounted under it."""
    from bot_program.engine.etoro_client import DemoOnlyEtoroTrader
    t = DemoOnlyEtoroTrader("api-k", "user-k")
    t._sess()
    t._session.mount("https://", transport)
    return t


def _account(user, *, demo=False):
    """The operator's eToro row, ticked for the REAL account on purpose:
    the runner must reach the demo segment whatever it says."""
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, demo=demo, label="Main")
    acct.set_credentials("api-k", "user-k")
    acct.save()
    return acct


def _switch(on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key="short_proofs_demo",
        defaults={"name": "t", "category": "pipeline", "is_enabled": on})


def _proof(asset_class="etf", leverage=1, *, symbol="GLDM", state="proven",
           proven=True, world="demo", source="proof_runner", side="short",
           revoked=False, at=None, **extra):
    from bot_program.short_models import EtoroShortObservation
    from django.utils import timezone
    return EtoroShortObservation.objects.create(
        asset_class=asset_class, symbol=symbol, world=world, side=side,
        settlement="CFD", leverage=leverage,
        units=extra.pop("units", Decimal("1")),
        order_id="1", position_id="2", source=source, proof_state=state,
        demo_proven=proven, read_at=at or timezone.now(),
        revoked_at=timezone.now() if revoked else None, **extra)


def _run(t, now, **kw):
    from bot_program import short_proofs
    with mock.patch("time.sleep"):
        return short_proofs.run_once(now=now, client=t, **kw)


class _Base(TestCase):

    def setUp(self):
        cache.clear()
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        self.user = User.objects.create_user("sp_u", password="x",
                                             is_staff=True)
        self.acct = _account(self.user)
        _switch(True)
        self.notify = self._patch(NOTIFY, return_value={"n_delivered": 1})
        self.alarm = self._patch(ALARM, return_value=True)

    def _patch(self, target, **kw):
        p = mock.patch(target, **kw)
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def _rows(self, **kw):
        from bot_program.short_models import EtoroShortObservation
        return list(EtoroShortObservation.objects.filter(
            source="proof_runner", **kw).order_by("pk"))


# ── the demo-only client ─────────────────────────────────────────────────

class TheDemoOnlyClientTests(SimpleTestCase):
    """How the client picks the world: EtoroTrader.demo, set from `env`,
    writes "demo/" into every trading URL (_seg, _v2, _v2_lookup ...), and
    the eligibility readers default to the LIVE world (world="live"). The
    runner's client pins the first and refuses the second, and every
    request it makes goes through a wire that refuses any URL off the demo
    segment before it leaves the box."""

    def setUp(self):
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_the_segment_is_demo_by_construction(self):
        t = _demo(_Wire())
        self.assertIs(t.demo, True)
        self.assertEqual(t.env, "demo")
        for url in (t._v2_exec_orders(), t._v2_lookup(),
                    t._v1_info("portfolio"), t._v1_info("pnl"),
                    t._v1_exec("market-close-orders/positions/1"),
                    t._v3_exec_order("1"), t._v2("positions/1"),
                    t._v2_info("eligibility")):
            self.assertIn("/demo/", url, url)

    def test_it_cannot_be_turned_to_the_real_segment(self):
        from bot_program.engine.etoro_client import RealSegmentRefused
        t = _demo(_Wire())
        with self.assertRaises(RealSegmentRefused):
            t.demo = False
        with self.assertRaises(RealSegmentRefused):
            t.env = "live"
        self.assertIs(t.demo, True)

    def test_a_real_segment_url_never_reaches_the_wire(self):
        from bot_program.engine.etoro_client import BASE, RealSegmentRefused
        wire = _Wire()
        t = _demo(wire)
        for method, tail in (
                ("post", "/api/v2/trading/execution/orders"),
                ("get", "/api/v2/trading/info/orders:lookup"),
                ("get", "/api/v1/trading/info/portfolio"),
                ("get", "/api/v1/trading/info/real/pnl"),
                ("post", "/api/v1/trading/execution/market-close-orders/"
                         "positions/1"),
                ("delete", "/api/v3/trading/execution/orders/1"),
                ("post", "/api/v2/trading/info/eligibility")):
            with self.subTest(tail=tail):
                with self.assertRaises(RealSegmentRefused):
                    getattr(t._sess(), method)(BASE + tail, json={})
        with self.assertRaises(RealSegmentRefused):
            t._sess().get("https://example.invalid/api/v1/market-data/x")
        self.assertEqual(wire.calls, [], "a real-segment URL left the box")

    def test_a_redirect_is_never_followed(self):
        """requests follows a redirect by default, and on a 307 or a 308
        it sends the same method and body again, the session's keys with
        them, to whatever Location says, inside Session.send, past the
        wire's check (the review of 2026-10-31). The wire asks for no
        redirect, whatever the caller passes, and refuses every 3xx
        answer: one request left, to the demo segment, and no other."""
        from bot_program.engine.etoro_client import BASE, RedirectRefused
        host = urlsplit(BASE).netloc
        for code, location in (
                (307, BASE + "/api/v2/trading/execution/orders"),
                (308, BASE + "/api/v2/trading/execution/orders"),
                (307, "https://other-host.invalid/api/v2/trading/"
                      "execution/demo/orders"),
                (301, BASE + "/api/v2/trading/execution/orders"),
                (302, BASE + "/api/v1/market-data/search"),
                (303, BASE + "/api/v2/trading/execution/orders"),
                (300, "")):
            with self.subTest(code=code, location=location):
                transport = _Transport(_Wire(), redirect={
                    ("POST", "/execution/demo/orders"): (code, location),
                    ("DELETE", "/execution/demo/orders/1"): (code, location),
                    ("GET", "/market-data/search"): (code, location)})
                t = _demo_over(transport)
                orders = t._v2_exec_orders()
                with self.assertRaises(RedirectRefused) as cm:
                    t._sess().post(orders, json={"transaction": "sellShort"},
                                   allow_redirects=True)
                self.assertEqual(cm.exception.status, code)
                self.assertEqual(transport.sent, [("POST", orders)])
                with self.assertRaises(RedirectRefused):
                    t._sess().delete(t._v3_exec_order("1"))
                with self.assertRaises(RedirectRefused):
                    t._sess().request("get",
                                      BASE + "/api/v1/market-data/search")
                self.assertEqual(len(transport.sent), 3, transport.sent)
                self.assertTrue(all(urlsplit(u).netloc == host
                                    and (m != "POST" or "/demo/" in u)
                                    for m, u in transport.sent),
                                transport.sent)
                self.assertEqual(t.wire_requests, 3)

    def test_the_live_world_reads_are_refused_before_the_wire(self):
        from bot_program.engine.etoro_client import RealSegmentRefused
        wire = _Wire(rows=[ROW_BTC])
        t = _demo(wire)
        with self.assertRaises(RealSegmentRefused):
            t.leverage_values("BTCUSD", "SELL", "cfd")   # world="live"
        with self.assertRaises(RealSegmentRefused):
            t.eligibility("BTCUSD", world="live")
        with self.assertRaises(RealSegmentRefused):
            t.min_amount("BTCUSD", "SELL", "cfd", 1)       # world="live"
        self.assertEqual(wire.calls, [])
        self.assertEqual(t.leverage_values("BTCUSD", "SELL", "cfd",
                                           world="demo"), [1, 2])
        self.assertTrue(all("/demo/" in u for u in wire.urls()
                            if "/trading/" in u), wire.urls())

    def test_the_market_data_family_carries_no_world_and_is_read(self):
        wire = _Wire()
        t = _demo(wire)
        self.assertEqual(t.ticker("BTCUSD")["lastPrice"], "60000.0")
        self.assertTrue(all("/market-data/" in u for u in wire.urls()))

    def test_it_is_no_carrier_of_any_lane(self):
        """capabilities.adapter_key reads the class name: no bot lane,
        ticket, gate or reconcile can mistake the runner's client for the
        trading client."""
        from bot_program.engine.capabilities import adapter_key
        self.assertEqual(adapter_key(_demo(_Wire())), "")


class TheBuilderTests(_Base):

    def test_the_runner_builds_a_demo_client_whatever_the_row_says(self):
        from bot_program import short_proofs
        from bot_program.engine.etoro_client import DemoOnlyEtoroTrader
        self.assertFalse(self.acct.demo, "the row is ticked for REAL money")
        t = short_proofs.demo_client(self.acct)
        self.assertIsInstance(t, DemoOnlyEtoroTrader)
        self.assertIs(t.demo, True)
        self.assertEqual(short_proofs.keyed_account(), self.acct)

    def test_no_keys_is_no_runner(self):
        from bot_program import short_proofs
        self.acct.api_key_enc = ""
        self.acct.save(update_fields=["api_key_enc"])
        self.assertIsNone(short_proofs.keyed_account())
        out = short_proofs.run_once(now=SUNDAY)
        self.assertEqual(out["status"], "skipped")
        self.assertIn("no eToro keys", out["reason"])


class TheRedirectTests(_Base):
    """THE REDIRECT (the review of 2026-10-31). A 307 or a 308 on the
    demo order POST went, in requests' own hands, to the Location with
    the same sellShort body and the operator's keys: the real segment, or
    another host. Now nothing follows a redirect: one request leaves, to
    the demo segment, and the runner reads an order or a close answered
    so as in doubt (whether eToro's demo account took it is unknown)."""

    def _transport(self, redirect):
        return _Transport(_Wire(rows=[ROW_BTC], lookups={7001: _round_trip()}),
                          redirect=redirect)

    def _clean(self):
        from bot_program.short_models import EtoroShortObservation
        EtoroShortObservation.objects.all().delete()
        self.alarm.reset_mock()
        self.notify.reset_mock()

    def test_a_redirected_order_is_not_followed_and_stops_the_runner(self):
        from bot_program.engine.etoro_client import BASE
        host = urlsplit(BASE).netloc
        for code in (307, 308):
            for location in (BASE + "/api/v2/trading/execution/orders",
                             "https://other-host.invalid/api/v2/trading/"
                             "execution/orders"):
                with self.subTest(code=code, location=location):
                    self._clean()
                    transport = self._transport({
                        ("POST", "/execution/demo/orders"): (code, location)})
                    t = _demo_over(transport)
                    out = _run(t, SUNDAY)
                    self.assertEqual(out["status"], "error", out)
                    orders = [u for m, u in transport.sent
                              if m == "POST" and "/execution/" in u]
                    self.assertEqual(orders, [t._v2_exec_orders()])
                    self.assertEqual(transport.sent[-1],
                                     ("POST", t._v2_exec_orders()),
                                     "a request left after the redirect")
                    self.assertTrue(all(urlsplit(u).netloc == host
                                        for _m, u in transport.sent))
                    [row] = self._rows()
                    self.assertEqual((row.proof_state, row.demo_proven),
                                     ("in_doubt", False))
                    self.assertIn(f"redirect (HTTP {code})", row.refusal)
                    self.assertIn("not followed", row.refusal)
                    self.alarm.assert_called_once()
                    # stopped: the next run sends nothing at all
                    again = self._transport({})
                    out = _run(_demo_over(again), SUNDAY + timedelta(hours=1))
                    self.assertEqual(out["status"], "error")
                    self.assertEqual(again.sent, [])

    def test_a_redirected_close_is_not_followed_and_is_in_doubt(self):
        from bot_program.engine.etoro_client import BASE
        transport = self._transport({
            ("POST", "/market-close-orders/positions/900001"):
                (307, BASE + "/api/v1/trading/execution/market-close-orders/"
                             "positions/900001")})
        out = _run(_demo_over(transport), SUNDAY)
        self.assertEqual(out["status"], "error", out)
        closes = [u for m, u in transport.sent
                  if m == "POST" and "market-close-orders" in u]
        self.assertEqual(len(closes), 1)
        self.assertIn("/demo/", closes[0])
        self.assertEqual(transport.sent[-1], ("POST", closes[0]))
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.demo_proven),
                         ("in_doubt", False))
        self.assertIn("close answered with a redirect (HTTP 307)",
                      row.refusal)
        self.alarm.assert_called_once()

    def test_a_redirected_read_sends_nothing_more(self):
        """A read answered with a redirect is unread: the step is skipped,
        nothing is recorded, nothing is followed."""
        from bot_program.engine.etoro_client import BASE
        transport = self._transport({
            ("POST", "/info/demo/eligibility"):
                (307, BASE + "/api/v2/trading/info/eligibility")})
        out = _run(_demo_over(transport), SUNDAY)
        self.assertEqual(out["status"], "skipped", out)
        self.assertIn("RedirectRefused", out["reason"])
        self.assertEqual(transport.sent[-1][0], "POST")
        self.assertIn("/info/demo/eligibility", transport.sent[-1][1])
        self.assertFalse(any(u.endswith("/info/eligibility")
                             for _m, u in transport.sent))
        self.assertEqual(self._rows(), [])
        self.alarm.assert_not_called()


# ── the happy path ───────────────────────────────────────────────────────

class TheRoundTripTests(_Base):
    """BTCUSD on a Sunday: crypto is the class whose market never shuts."""

    def _wire(self, **kw):
        kw.setdefault("rows", [ROW_BTC])
        kw.setdefault("lookups", {7001: _round_trip()})
        return _Wire(**kw)

    def test_a_crypto_short_round_trip_is_recorded_and_opens_the_gate(self):
        from bot_program.asset_engine.base import missing_proofs
        self.assertEqual(missing_proofs("crypto", "SELL"), ["short_crypto"])
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        [row] = self._rows()
        self.assertEqual((row.asset_class, row.symbol, row.world, row.side,
                          row.leverage, row.proof_state, row.demo_proven),
                         ("crypto", "BTCUSD", "demo", "short", 1, "proven",
                          True))
        self.assertEqual(row.units, Decimal("0.0002"),
                         "the venue minimum: 10 USD (+5%) at 60,000, "
                         "rounded up to the coin's step")
        self.assertEqual((row.order_id, row.position_id,
                          row.close_order_id), ("7001", "900001", "8001"))
        self.assertIsNotNone(row.closed_at)
        self.assertEqual(row.open_rate, Decimal("60000.0"))
        self.assertGreater(row.requests, 0)
        # one sell, one close, both on the demo segment
        [order] = [k for m, u, k in wire.calls
                   if m == "POST" and u.endswith("/orders")]
        body = order["json"]
        self.assertEqual((body["transaction"], body["symbol"], body["units"],
                          body["leverage"]), ("sellShort", "BTC", 0.0002, 1))
        self.assertGreater(body["stopLossRate"], 60000.0)
        self.assertLess(body["takeProfitRate"], 60000.0)
        closes = [u for m, u in [(m, u) for m, u, _k in wire.calls]
                  if m == "POST" and "market-close-orders" in u]
        self.assertEqual(len(closes), 1)
        for url in wire.urls():
            if "/trading/" in url:
                self.assertIn("/demo/", url)
        # the account keys never ride the record
        self.assertNotIn("CID", row.close_lookup.get("close", {}).get(
            "orderForClose", {}))
        # the operator is told, in his words
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.kwargs["title"],
                         TITLE.format(cls="crypto", lev=1))
        self.assertIsNotNone(row.notified_at)
        self.alarm.assert_not_called()
        # and the bots' gate reads it at 1x, and only at 1x
        self.assertEqual(missing_proofs("crypto", "SELL"), [])
        self.assertEqual(missing_proofs("crypto", "SELL", leverage=1), [])
        self.assertEqual(missing_proofs("crypto", "SELL", leverage=2),
                         ["short_crypto"])

    def test_the_next_run_is_spaced_out(self):
        _run(_demo(self._wire()), SUNDAY)
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY + timedelta(minutes=10))
        self.assertEqual(out["status"], "skipped")
        self.assertIn("spaced", out["reason"])
        self.assertEqual(wire.urls("POST"), [])
        self.assertEqual(len(self._rows()), 1)

    def test_then_two_x_where_the_row_lists_it_and_five_x_is_not_offered(self):
        _run(_demo(self._wire()), SUNDAY)
        wire = self._wire(lookups={7001: _round_trip(units=0.0004,
                                                     leverage=2)})
        out = _run(_demo(wire), SUNDAY + timedelta(minutes=30))
        self.assertEqual(out["status"], "success", out)
        [order] = [k["json"] for m, u, k in wire.calls
                   if m == "POST" and u.endswith("/orders")]
        self.assertEqual((order["leverage"], order["units"]), (2, 0.0004),
                         "at 2x the margin floor (2 x 10) sets the size")
        row = self._rows()[-1]
        self.assertEqual((row.leverage, row.proof_state, row.demo_proven),
                         (2, "proven", True))
        self.assertEqual(self.notify.call_args.kwargs["title"],
                         TITLE.format(cls="crypto", lev=2))
        # the body names every multiplier the gate now lets through
        self.assertIn("lets a crypto short through at 1x, 2x only",
                      self.notify.call_args.kwargs["body"])
        # 5x: the demo row lists [1, 2] for a BTC short
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY + timedelta(minutes=60))
        self.assertEqual([u for u in wire.urls("POST")
                          if u.endswith("/orders")], [])
        row = self._rows()[-1]
        self.assertEqual((row.leverage, row.proof_state, row.demo_proven),
                         (5, "not_listed", False))
        from bot_program.asset_engine.base import missing_proofs
        self.assertEqual(missing_proofs("crypto", "SELL", leverage=5),
                         ["short_crypto"])

    def test_a_proof_is_announced_once(self):
        """The same (class, multiplier) proven again by hand is not news."""
        _proof("crypto", 1, symbol="BTCUSD")
        out = _run(_demo(self._wire()), SUNDAY, asset_class="crypto",
                   leverage=1)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual(self._rows()[-1].proof_state, "proven")
        self.notify.assert_not_called()

    def test_one_class_at_a_time_and_closes_first(self):
        """A position the runner holds is closed before anything else is
        opened, and that run opens nothing."""
        held = _proof("crypto", 1, symbol="BTCUSD", state="open",
                      proven=False, at=SUNDAY - timedelta(hours=1))
        held.order_id, held.position_id = "7001", "900001"
        held.save(update_fields=["order_id", "position_id"])
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual([u for u in wire.urls("POST")
                          if u.endswith("/orders")], [], "it opened")
        self.assertEqual(len([u for u in wire.urls("POST")
                              if "market-close-orders" in u]), 1)
        held.refresh_from_db()
        self.assertIsNotNone(held.closed_at)


# ── what refuses ─────────────────────────────────────────────────────────

class TheRefusalTests(_Base):

    def test_a_shut_market_sends_nothing(self):
        wire = _Wire(rows=[ROW_GLDM])
        out = _run(_demo(wire), SATURDAY, asset_class="etf")
        self.assertEqual(out["status"], "skipped")
        self.assertIn("shut", out["reason"])
        self.assertEqual(wire.calls, [])
        self.assertEqual(self._rows(), [])

    def test_an_index_outside_new_yorks_session_sends_nothing(self):
        """The demo index SELLs of 2026-10-01 were sent at 21:01 and 21:17
        UTC and refused (749) inside the US index futures' break: the
        runner waits for New York's own session."""
        wire = _Wire(rows=[ROW_SPX])
        evening = datetime(2026, 11, 2, 22, 30, tzinfo=UTC)
        out = _run(_demo(wire), evening, asset_class="index")
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(wire.calls, [])

    def test_the_rollover_sends_nothing(self):
        wire = _Wire(rows=[ROW_GOLD])
        roll = datetime(2026, 11, 2, 21, 55, tzinfo=UTC)   # 16:55 New York
        out = _run(_demo(wire), roll, asset_class="commodity")
        self.assertEqual(out["status"], "skipped")
        self.assertIn("rolls over", out["reason"])
        self.assertEqual(wire.calls, [])

    def test_an_order_post_that_did_not_come_back_stops_everything(self):
        wire = _Wire(rows=[ROW_BTC], raise_on={
            ("POST", "/execution/demo/orders"):
                requests.exceptions.ReadTimeout("read timed out")})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "error", out)
        self.assertIn("in doubt", out["error"])
        self.assertEqual(len([u for u in wire.urls("POST")
                              if u.endswith("/orders")]), 1,
                         "the POST was sent again")
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.demo_proven),
                         ("in_doubt", False))
        self.alarm.assert_called_once()
        title, lines = self.alarm.call_args.args[:2]
        self.assertIn("in doubt", title)
        self.assertTrue(any("demo" in str(x) for x in lines))
        self.assertTrue(self.notify.called)
        # the next run sends nothing at all
        wire2 = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire2), SUNDAY + timedelta(hours=2))
        self.assertEqual(out["status"], "error")
        self.assertIn("stopped", out["error"])
        self.assertEqual(wire2.calls, [])

    def test_a_close_post_that_did_not_come_back_stops_too(self):
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()},
                     raise_on={("POST", "market-close-orders"):
                               requests.exceptions.ReadTimeout("timed out")})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(len([u for u in wire.urls("POST")
                              if "market-close-orders" in u]), 1)
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.demo_proven),
                         ("in_doubt", False))
        self.alarm.assert_called_once()
        from bot_program.asset_engine.base import missing_proofs
        self.assertEqual(missing_proofs("crypto", "SELL"), ["short_crypto"])

    def test_a_fill_nobody_could_read_is_in_doubt(self):
        """Every orders:lookup of the fill poll failed (pollFailed): the
        order may have filled, so nothing more is sent."""
        wire = _Wire(rows=[ROW_BTC], lookups={7001: [(500, {})]})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "error")
        [row] = self._rows()
        self.assertEqual(row.proof_state, "in_doubt")
        self.assertEqual([u for u in wire.urls("POST")
                          if "market-close-orders" in u], [])

    def test_a_server_error_on_the_order_post_is_in_doubt(self):
        wire = _Wire(rows=[ROW_BTC], order_status=503)
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "error")
        self.assertEqual(self._rows()[0].proof_state, "in_doubt")

    def test_an_accepted_order_nobody_can_read_is_in_doubt(self):
        """A 2xx is an acceptance (fact 1 of the client). One whose body is
        not JSON (an empty 202, an HTML page) may hold a short at eToro's
        demo account: in doubt, the runner stops and the alarm rings, and
        the next run sends no other SELL (the review of 2026-10-31: it was
        filed not_sent, back-off 0, and sold again 25 minutes later)."""
        wire = _UnreadAcceptance(rows=[ROW_BTC])
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "error", out)
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.demo_proven),
                         ("in_doubt", False))
        self.assertIn("answered HTTP 202 with a body nobody could read",
                      row.refusal)
        self.alarm.assert_called_once()
        again = _UnreadAcceptance(rows=[ROW_BTC])
        out = _run(_demo(again), SUNDAY + timedelta(minutes=30))
        self.assertEqual(out["status"], "error")
        self.assertEqual(again.calls, [])

    def test_only_the_adapters_own_refusal_is_read_as_not_sent(self):
        """A ValueError is "nothing left the box" only when the adapter says
        so: "eToro NOT SENT: ...", raised before its POST. Any other
        ValueError out of the order call may come after an accepted POST
        (a body json() could not read): in doubt."""
        from bot_program.short_models import EtoroShortObservation
        for text, state in (
                ("eToro NOT SENT: leverage 2 with no stop_loss (BTCUSD SELL)",
                 "not_sent"),
                ("Expecting value: line 1 column 1 (char 0)", "in_doubt")):
            with self.subTest(text=text):
                EtoroShortObservation.objects.all().delete()
                t = _demo(_Wire(rows=[ROW_BTC]))
                with mock.patch.object(t, "market_order",
                                       side_effect=ValueError(text)):
                    _run(t, SUNDAY)
                [row] = self._rows()
                self.assertEqual(row.proof_state, state)

    def test_a_venue_minimum_past_the_rows_maximum_units_is_refused_unsent(
            self):
        row = _elig_row(100000, "BTC", [
            _lev("real", "long", [1], max_sl=100),
            _lev("cfd", "long", [2]),
            _lev("cfd", "short", [1, 2])], max_units=0.0001, w8=False)
        wire = _Wire(rows=[row], lookups={7001: _round_trip()})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual([u for u in wire.urls("POST")
                          if u.endswith("/orders")], [])
        [rec] = self._rows()
        self.assertEqual((rec.proof_state, rec.demo_proven),
                         ("refused", False))
        self.assertIn("maxUnitsPerOrder", rec.refusal)

    def test_a_held_order_whose_withdrawal_is_not_proven_is_in_doubt(self):
        """eToro held the SELL (WaitingForMarket) and the DELETE was not
        proven: the lookup read it still held afterwards, or could not be
        read at all. The order may still fill: in doubt."""
        from bot_program.short_models import EtoroShortObservation
        waiting = _short_lookup(order=7001, status_id=11, executions=False)
        waiting["status"] = {"id": 11, "name": "WaitingForMarket",
                             "errorCode": 0}
        for name, after in (("still held", [(200, waiting)]),
                            ("unread", [(500, {})])):
            with self.subTest(after=name):
                EtoroShortObservation.objects.all().delete()
                self.alarm.reset_mock()
                wire = _Wire(rows=[ROW_BTC], lookups={
                    7001: [(200, waiting)] * 6 + after})
                out = _run(_demo(wire), SUNDAY)
                self.assertEqual(out["status"], "error", out)
                self.assertEqual(len(wire.urls("DELETE")), 1)
                [row] = self._rows()
                self.assertEqual(row.proof_state, "in_doubt")
                self.assertIn("withdrawal was not proven", row.refusal)
                self.alarm.assert_called_once()

    def test_a_held_lock_sends_nothing(self):
        from bot_program import short_proofs
        cache.add(short_proofs.LOCK_KEY, 1, short_proofs.LOCK_S)
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "skipped", out)
        self.assertIn("holds its lock", out["reason"])
        self.assertEqual(wire.calls, [])
        self.assertEqual(self._rows(), [])
        self.assertTrue(cache.get(short_proofs.LOCK_KEY),
                        "another pass's lock was released by this one")

    def test_a_hold_of_one_class_holds_every_other_class(self):
        """One class at a time: while an ETF short is held across the
        close at eToro's demo account, no other class's step opens (the
        review of 2026-10-31: the held check read the step's own class
        only, so crypto went on for the whole hold)."""
        from bot_program import short_proofs
        held = _proof("etf", 1, symbol="GLDM", state="open", proven=False,
                      overnight=True, at=SUNDAY - timedelta(hours=2),
                      hold_until=SUNDAY + timedelta(hours=20))
        held.order_id, held.position_id = "7001", "900001"
        held.save(update_fields=["order_id", "position_id"])
        wire = _Wire(rows=[ROW_BTC], accept=[7002],
                     lookups={7002: _round_trip(order=7002)})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "skipped", out)
        self.assertIn("one class at a time", out["reason"])
        self.assertEqual(wire.calls, [])
        crypto = [s for s in short_proofs.plan(now=SUNDAY)
                  if s["asset_class"] == "crypto" and s["leverage"] == 1
                  and not s["overnight"]][0]
        self.assertEqual(crypto["state"], "held")
        self.assertIn("an ETF short is held (GLDM)", crypto["why"])
        # a step named by hand waits for it too
        out = _run(_demo(wire), SUNDAY, asset_class="crypto", leverage=1)
        self.assertEqual(out["status"], "skipped", out)
        self.assertEqual(wire.calls, [])

    def test_three_closes_none_proven_is_in_doubt_and_no_fourth_is_sent(self):
        held = _proof("crypto", 1, symbol="BTCUSD", state="open",
                      proven=False, at=SUNDAY - timedelta(hours=1))
        held.order_id, held.position_id = "7001", "900001"
        held.save(update_fields=["order_id", "position_id"])
        still_open = (200, _short_lookup(state="open", order=7001,
                                         position=900001, units=0.0002))
        closes = 0
        for i in range(4):
            wire = _Wire(rows=[ROW_BTC], lookups={7001: [still_open]})
            _run(_demo(wire), SUNDAY + timedelta(minutes=30 * i))
            closes += len([u for u in wire.urls("POST")
                           if "market-close-orders" in u])
        self.assertEqual(closes, 3)
        held.refresh_from_db()
        self.assertEqual((held.proof_state, held.demo_proven),
                         ("in_doubt", False))
        self.assertIn("was sent 3 closes and none was proven", held.refusal)
        self.alarm.assert_called_once()

    def test_a_close_shown_closed_on_the_next_pass_needs_no_second_close(
            self):
        """A close eToro had not shown closed (CLOSING) is read again on
        the next pass, by the open order's state, before any other close
        is sent."""
        held = _proof("crypto", 1, symbol="BTCUSD", state="closing",
                      proven=False, at=SUNDAY - timedelta(hours=1),
                      close_lookup={"verdict": "clean", "facts": [],
                                    "held_at_fill": {}, "close_attempts": 1})
        held.order_id, held.position_id = "7001", "900001"
        held.save(update_fields=["order_id", "position_id"])
        wire = _Wire(rows=[ROW_BTC], lookups={7001: [
            (200, _short_lookup(state="closed", order=7001, position=900001,
                                units=0.0002))]})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual([u for u in wire.urls("POST")
                          if "market-close-orders" in u], [])
        held.refresh_from_db()
        self.assertEqual((held.proof_state, held.demo_proven),
                         ("proven", True))

    def test_a_sick_venue_or_a_pending_real_close_goes_first(self):
        from bot_program import venue_health
        for _ in range(3):
            venue_health.note("etoro", "live", "ticker", code=503)
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "skipped")
        self.assertIn("sick", out["reason"])
        self.assertEqual(wire.calls, [])
        venue_health.reset()
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="sp_live", mode="live",
            symbols=["AAPL"], capital=Decimal("1000"))
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            status="CLOSE_PENDING", paper=False, rule_name="r")
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "skipped")
        self.assertIn("close", out["reason"])
        self.assertEqual(wire.calls, [])

    def test_the_runners_own_close_waits_on_the_live_lane_too(self):
        """Demo money waits: a held demo position is not closed while eToro
        is sick; it is closed on the first pass after."""
        from bot_program import venue_health
        held = _proof("crypto", 1, symbol="BTCUSD", state="open",
                      proven=False, at=SUNDAY - timedelta(hours=1))
        held.order_id, held.position_id = "7001", "900001"
        held.save(update_fields=["order_id", "position_id"])
        for _ in range(3):
            venue_health.note("etoro", "live", "ticker", code=429)
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(wire.calls, [])
        venue_health.reset()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(len([u for u in wire.urls("POST")
                              if "market-close-orders" in u]), 1)

    def test_a_step_that_died_between_its_order_and_the_answer_is_in_doubt(
            self):
        """A row still "sending" five minutes on: the process stopped after
        the POST, so whether eToro holds a position is unknown."""
        _proof("crypto", 1, symbol="BTCUSD", state="sending", proven=False,
               at=SUNDAY - timedelta(minutes=6))
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "error")
        self.assertEqual(wire.calls, [])
        self.assertEqual(self._rows()[0].proof_state, "in_doubt")
        self.alarm.assert_called_once()

    def test_an_instrument_etoro_does_not_know_is_not_asked_again_today(self):
        wire = _Wire(rows=[ROW_BTC])
        with mock.patch.dict(SEARCH, {"BTC": None}):
            out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        [row] = self._rows()
        self.assertEqual(row.proof_state, "no_row")
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), SUNDAY + timedelta(hours=2))
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(wire.calls, [])
        out = _run(_demo(wire), SUNDAY + timedelta(hours=25))
        self.assertEqual(self._rows()[-1].proof_state, "proven", out)

    def test_a_refused_index_sell_is_recorded_and_the_next_index_is_tried(
            self):
        refused = {"status": {"id": 4, "name": "Rejected", "errorCode": 749,
                              "errorMessage": "disallowed for instrument"},
                   "positionExecutions": []}
        wire = _Wire(rows=[ROW_SPX, ROW_NSDQ],
                     lookups={7001: [(200, refused)]})
        out = _run(_demo(wire), MONDAY, asset_class="index")
        self.assertEqual(out["status"], "success", out)
        [row] = self._rows()
        self.assertEqual((row.symbol, row.proof_state, row.demo_proven),
                         ("SPX500", "refused", False))
        self.assertIn("749", row.refusal)
        self.assertEqual([u for u in wire.urls("POST")
                          if "market-close-orders" in u], [])
        wire = _Wire(rows=[ROW_SPX, ROW_NSDQ], accept=[7002],
                     lookups={7002: _round_trip(
                         order=7002, symbol="NSDQ100", iid=28, units=1.0,
                         avg=21000.0)})
        out = _run(_demo(wire), MONDAY + timedelta(minutes=30),
                   asset_class="index")
        self.assertEqual(out["status"], "success", out)
        row = self._rows()[-1]
        self.assertEqual((row.symbol, row.proof_state, row.demo_proven),
                         ("NSDQ100", "proven", True))

    def test_an_order_eToro_holds_for_the_market_is_withdrawn(self):
        waiting = _short_lookup(order=7001, status_id=11, executions=False)
        waiting["status"] = {"id": 11, "name": "WaitingForMarket",
                             "errorCode": 0}
        cancelled = dict(waiting, status={"id": 7, "name": "Canceled",
                                          "errorCode": 0})
        wire = _Wire(rows=[ROW_BTC], lookups={
            7001: [(200, waiting)] * 6 + [(200, cancelled)]})
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual(len(wire.urls("DELETE")), 1)
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.demo_proven),
                         ("withdrawn", False))

    def test_a_row_with_no_short_entry_is_recorded_and_nothing_is_sent(self):
        wire = _Wire(rows=[ROW_GLDM_NO_SHORT])
        out = _run(_demo(wire), MONDAY, asset_class="etf")
        self.assertEqual([u for u in wire.urls("POST")
                          if u.endswith("/orders")], [])
        [row] = self._rows()
        self.assertEqual((row.symbol, row.proof_state), ("GLDM", "no_short"))
        self.assertIn("no short", row.refusal)
        self.assertEqual(out["status"], "success")

    def test_a_class_whose_short_is_pinned_in_code_is_not_run(self):
        from bot_program import short_proofs
        steps = short_proofs.plan(now=MONDAY)
        self.assertNotIn("stock", {s["asset_class"] for s in steps})
        self.assertNotIn("forex", {s["asset_class"] for s in steps})
        self.assertEqual([s["asset_class"] for s in steps
                          if s["leverage"] == 1 and not s["overnight"]],
                         ["crypto", "etf", "index", "commodity"])


# ── each rule of the clock and of the budget, at a fixed time ────────────

class TheClockTests(_Base):
    """Each rule that holds a step back, at a fixed clock: the step sends
    nothing and the reason names the rule (the review of 2026-10-31: each
    could be removed with the suite still green)."""

    def _etf(self, now, **kw):
        wire = _Wire(rows=[ROW_GLDM], lookups={7001: _round_trip(
            symbol="GLDM", iid=3190, units=1.0, avg=80.0)})
        return _run(_demo(wire), now, asset_class="etf", **kw), wire

    def test_a_market_open_less_than_its_settle_sends_nothing(self):
        # Monday 2 November 2026, 09:40 New York: open for ten minutes
        out, wire = self._etf(datetime(2026, 11, 2, 14, 40, tzinfo=UTC))
        self.assertEqual(out["status"], "skipped", out)
        self.assertIn("opened less than 15 minutes ago", out["reason"])
        self.assertEqual(wire.calls, [])

    def test_a_markets_last_30_minutes_send_nothing(self):
        # Monday 2 November 2026, 15:45 New York: it closes at 16:00
        out, wire = self._etf(datetime(2026, 11, 2, 20, 45, tzinfo=UTC))
        self.assertEqual(out["status"], "skipped", out)
        self.assertIn("closes within 30 minutes", out["reason"])
        self.assertEqual(wire.calls, [])

    def test_one_429_within_ten_minutes_holds_every_step(self):
        """One 429 does not make eToro sick (three do); the runner still
        stays away for YIELD_AFTER_429_S, on either world."""
        from django.utils import timezone

        from bot_program import venue_health
        for world in ("live", "demo"):
            with self.subTest(world=world):
                venue_health.reset()
                venue_health.note("etoro", world, "ticker", code=429,
                                  now=timezone.now() - timedelta(minutes=5))
                self.assertIsNone(venue_health.sick("etoro", world))
                wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
                out = _run(_demo(wire), SUNDAY)
                self.assertEqual(out["status"], "skipped", out)
                self.assertIn(f"eToro ({world}) answered HTTP 429 within "
                              f"the last 10 minutes", out["reason"])
                self.assertEqual(wire.calls, [])
        venue_health.reset()

    def test_a_429_pause_holds_every_step(self):
        from bot_program.engine import etoro_client as ec
        for world in ("live", "demo"):
            with self.subTest(world=world), \
                    mock.patch.object(ec, "RATE_PAUSE", True), \
                    mock.patch.dict(ec._RATE_PAUSE,
                                    {world: ec._mono() + 60}, clear=True):
                wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
                out = _run(_demo(wire), SUNDAY)
                self.assertEqual(out["status"], "skipped", out)
                self.assertIn(f"eToro ({world}) is in its 429 pause",
                              out["reason"])
                self.assertEqual(wire.calls, [])

    def test_an_overnight_hold_never_opens_on_a_friday(self):
        """Monday to Thursday only: one night, never a weekend. Even named
        by hand."""
        _proof("crypto", 1, symbol="BTCUSD")
        friday = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)   # 11:00 New York
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), friday, asset_class="crypto", overnight=True)
        self.assertEqual(out["status"], "skipped", out)
        self.assertIn("Monday to Thursday only", out["reason"])
        self.assertEqual(wire.calls, [])


class TheNightsTests(SimpleTestCase):

    def test_a_night_is_new_yorks_1700_on_new_yorks_own_clock(self):
        """The nights a hold paid are New York's 17:00 rollovers, which
        move with New York's summer time: 21:00 UTC in July, 22:00 UTC in
        November."""
        from bot_program.short_proofs import nights_between

        def at(*a):
            return datetime(*a, tzinfo=UTC)
        self.assertEqual(nights_between(at(2026, 7, 14, 20, 30),
                                        at(2026, 7, 14, 21, 30)), 1)
        self.assertEqual(nights_between(at(2026, 7, 14, 21, 30),
                                        at(2026, 7, 14, 22, 30)), 0)
        self.assertEqual(nights_between(at(2026, 11, 3, 21, 30),
                                        at(2026, 11, 3, 22, 30)), 1)
        self.assertEqual(nights_between(at(2026, 11, 3, 20, 30),
                                        at(2026, 11, 3, 21, 30)), 0)
        self.assertEqual(nights_between(at(2026, 11, 2, 17, 0),
                                        at(2026, 11, 4, 17, 0)), 2)
        self.assertEqual(nights_between(at(2026, 11, 2, 17, 0),
                                        at(2026, 11, 2, 17, 0)), 0)


# ── the bots' gate ───────────────────────────────────────────────────────

class TheGateTests(_Base):

    def _gate(self, symbol="GLDM", icls="etf", side="SELL", **kw):
        from bot_program.asset_engine.base import AssetBot
        from tests.test_etoro_client import _client
        t, _fake = _client([])
        return AssetBot._etoro_entry_refusal(t, symbol, side, 1.0, 80.0,
                                             icls, **kw)

    def test_a_recorded_demo_proof_opens_the_bots_gate_at_its_leverage_only(
            self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import missing_proofs
        code, why = self._gate()
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("short_etf", why)
        _proof("etf", 1)
        self.assertEqual(missing_proofs("etf", "SELL"), [])
        self.assertEqual(self._gate(), ("", ""))
        self.assertEqual(self._gate(leverage_hint=1), ("", ""))
        code, why = self._gate(leverage_hint=2)
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("short_etf", why)
        _proof("etf", 2)
        self.assertEqual(missing_proofs("etf", "SELL", leverage=2), [])
        # past the proof step: a 2x order on a row this fake never answers
        # meets the venue row's own step (the LIVE list unread)
        code, why = self._gate(leverage_hint=2)
        self.assertNotEqual(code, skips.GATE_BLOCKED, why)
        # another class is not opened by it
        self.assertEqual(missing_proofs("index", "SELL"), ["short_index"])

    def test_a_revoked_live_readback_or_unproven_row_opens_nothing(self):
        from bot_program.asset_engine.base import missing_proofs
        _proof("etf", 1, revoked=True)
        _proof("etf", 1, world="live")
        _proof("etf", 1, source="readback")
        _proof("etf", 1, proven=False, state="mismatch")
        _proof("etf", 1, side="long")
        self.assertEqual(missing_proofs("etf", "SELL"), ["short_etf"])

    def test_an_unreadable_record_opens_nothing(self):
        from bot_program.asset_engine.base import missing_proofs
        _proof("etf", 1)
        with mock.patch("bot_program.short_proofs.proven_leverages",
                        side_effect=RuntimeError("db down")):
            self.assertEqual(missing_proofs("etf", "SELL"), ["short_etf"])

    def test_a_class_proof_is_still_needed(self):
        from bot_program.asset_engine.base import missing_proofs
        _proof("etf", 1)
        with mock.patch(PROVEN, frozenset({"stock"})):
            self.assertEqual(missing_proofs("etf", "SELL"), ["etf"])

    def test_the_chooser_stays_on_a_measured_short_multiplier(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_attack_mode import _wire
        from tests.test_etoro_leverage import _switch as _lev_switch
        from tests.test_execution_trust import _cfg, _instrument
        _instrument("GLDM", "etf")
        cfg = _cfg(self.user, name="SPG")
        cfg.extras = {"leverage": "auto"}
        cfg.save(update_fields=["extras"])
        _lev_switch(True)
        bot = StockBot(cfg)
        row = _elig_row(3190, "GLDM", [
            _lev("cfd", "long", [1], max_sl=100),
            _lev("cfd", "short", [1, 2, 5])])
        _proof("etf", 1)
        _proof("etf", 2)
        lev, why = bot._choose_auto_leverage(_wire({"GLDM": row}), "GLDM",
                                             "SELL", 80.0, 80.4)
        self.assertEqual(lev, 2, why)
        self.assertIn("demo account", why)
        # a code-pinned short is not bounded by the record
        with mock.patch(SHORTS, frozenset({"etf"})):
            lev, _why = bot._choose_auto_leverage(
                _wire({"GLDM": row}), "GLDM", "SELL", 80.0, 80.4)
        self.assertEqual(lev, 5)

    def test_the_order_multiplier_must_be_a_measured_one(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_attack_mode import _wire
        from tests.test_etoro_leverage import _book
        from tests.test_etoro_leverage import _switch as _lev_switch
        from tests.test_execution_trust import _cfg, _instrument
        _instrument("GLDM", "etf")
        _book(self.user)
        cfg = _cfg(self.user, name="SPO")
        cfg.extras = {"leverage": 5}
        cfg.save(update_fields=["extras"])
        _lev_switch(True)
        bot = StockBot(cfg)
        row = _elig_row(3190, "GLDM", [
            _lev("cfd", "long", [1], max_sl=100),
            _lev("cfd", "short", [1, 2, 5])])
        _proof("etf", 1)
        lev, why = bot._order_leverage(_wire({"GLDM": row}), "GLDM",
                                       side="SELL", price=80.0, stop=80.4)
        self.assertIsNone(lev)
        self.assertIn("demo account at 1x only", why)
        self.assertIn("nothing sent at 5x", why)
        # a measured multiplier goes
        _proof("etf", 5)
        lev, why = bot._order_leverage(_wire({"GLDM": row}), "GLDM",
                                       side="SELL", price=80.0, stop=80.4)
        self.assertEqual((lev, why), (5, ""))

    def test_a_hand_taken_short_is_warned_and_read_back_off_the_measured_multiplier(
            self):
        """The TAKE TRADE lane's warning before the PIN and its read-back at
        the fill (S1) read the ticket's own multiplier: a short proven on
        the demo account at 1x is measured at 1x, and still warned and
        read back at 2x."""
        from bot_program import short_readback
        from tests.test_etoro_client import _client
        t, _fake = _client([])
        self.assertTrue(short_readback.unmeasured(t, "etf", "SELL"))
        _proof("etf", 1)
        self.assertFalse(short_readback.unmeasured(t, "etf", "SELL"))
        self.assertFalse(short_readback.unmeasured(t, "etf", "SELL",
                                                   leverage=1))
        self.assertTrue(short_readback.unmeasured(t, "etf", "SELL",
                                                  leverage=2))
        quiet = short_readback.ticket_advisory(t, "etf", "SELL", leverage=1)
        self.assertTrue(quiet["ok"])
        warned = short_readback.ticket_advisory(t, "etf", "SELL", leverage=2)
        self.assertFalse(warned["ok"])
        self.assertIn("First shorts on ETFs", warned["reason"])

    def test_morgul_reads_the_recorded_proof_at_the_rows_multiplier(self):
        from bot_program import morgul
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from tests.test_execution_trust import _instrument
        _instrument("GLDM", "etf")
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="sp_g5", mode="live",
            symbols=["GLDM"], capital=Decimal("1000"))
        _proof("etf", 1)
        for lev in (1, 2):
            AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol="GLDM", side="SELL",
                qty=Decimal("1"), entry_price=Decimal("80"), status="OPEN",
                paper=False, rule_name="bot_rule",
                metadata={"broker": "etoro", "leverage": lev})
        g = morgul.GUARD["proofs"]
        ctx = morgul.Context(now=MONDAY)
        found = morgul.check_proofs(ctx, g)
        self.assertEqual(len(found), 1, [f.facts for f in found])
        self.assertIn("Short selling", " ".join(found[0].facts))


# ── revoking ─────────────────────────────────────────────────────────────

class TheRevokeTests(_Base):

    def setUp(self):
        super().setUp()
        from tests.test_switch_pin import _set_pin
        self.admin = User.objects.create_superuser(
            "sp_admin", "sp_admin@example.test", "pw-of-the-test")
        _set_pin(self.admin)
        self.client.force_login(self.admin)

    def _revoke(self, row, pin, reason="checked by hand"):
        return self.client.post(f"/short-proofs/{row.pk}/revoke/",
                                {"pin": pin, "reason": reason})

    def test_a_superuser_revokes_with_the_pin_and_an_audit_row(self):
        from bot_program.asset_engine.base import missing_proofs
        from bot_program.audit_models import AuditLogEntry
        from tests.test_switch_pin import TEST_PIN
        row = _proof("etf", 1)
        self.assertEqual(missing_proofs("etf", "SELL"), [])
        resp = self._revoke(row, TEST_PIN)
        self.assertEqual(resp.status_code, 302)
        row.refresh_from_db()
        self.assertIsNotNone(row.revoked_at)
        self.assertEqual(row.revoked_by, self.admin)
        self.assertEqual(row.revoke_reason, "checked by hand")
        self.assertEqual(missing_proofs("etf", "SELL"), ["short_etf"])
        [audit] = AuditLogEntry.objects.filter(kind="short_proof_revoked")
        self.assertEqual(audit.user, self.admin)
        self.assertEqual((audit.data["asset_class"], audit.data["leverage"]),
                         ("etf", 1))
        self.assertNotIn("order_id", audit.data)

    def test_a_revoke_closes_the_multiplier_whatever_row_proved_it(self):
        """The gate opens a multiplier on ANY standing demo proof of it, and
        a class's 1x is proven twice in the normal sequence (the round
        trip, then the overnight hold, itself a clean 1x fill-and-close),
        more when a step is run again by hand. One revoke closes the
        (class, multiplier): every standing proof of it, one audit row
        naming them all, and the flash says what the gate does now (the
        review of 2026-10-31: one row was revoked, the gate stayed open)."""
        from bot_program import short_proofs
        from bot_program.asset_engine.base import missing_proofs
        from bot_program.audit_models import AuditLogEntry
        from tests.test_switch_pin import TEST_PIN
        trip = _proof("crypto", 1, symbol="BTCUSD")
        night = _proof("crypto", 1, symbol="BTCUSD", overnight=True, nights=1,
                       overnight_fee=Decimal("0.01"))
        again = _proof("crypto", 1, symbol="BTCUSD")     # run again by hand
        two = _proof("crypto", 2, symbol="BTCUSD")
        self.assertEqual(missing_proofs("crypto", "SELL", 1), [])
        resp = self._revoke(trip, TEST_PIN)
        self.assertEqual(resp.status_code, 302)
        for row in (trip, night, again):
            row.refresh_from_db()
            self.assertIsNotNone(row.revoked_at, row.pk)
            self.assertEqual(row.revoked_by, self.admin)
        two.refresh_from_db()
        self.assertIsNone(two.revoked_at, "2x is a pair of its own")
        self.assertEqual(missing_proofs("crypto", "SELL", 1),
                         ["short_crypto"])
        self.assertEqual(missing_proofs("crypto", "SELL", 2), [])
        words = dict(short_proofs.gate_words())["crypto"]
        self.assertIn("at 2x:", words)
        self.assertNotIn("1x", words)
        [audit] = AuditLogEntry.objects.filter(kind="short_proof_revoked")
        self.assertEqual(sorted(audit.data["rows"]),
                         sorted([trip.pk, night.pk, again.pk]))
        self.assertEqual(audit.data["leverage"], 1)
        flash = [str(m) for m in get_messages(resp.wsgi_request)][-1]
        self.assertIn("3 standing proofs", flash)
        self.assertIn("the bots' gate now refuses a bot short of crypto at "
                      "1x", flash)
        self.assertIn("it still lets one through at 2x", flash)
        # the same act on 2x: nothing stands at any multiplier
        resp = self._revoke(two, TEST_PIN)
        flash = [str(m) for m in get_messages(resp.wsgi_request)][-1]
        self.assertIn("its one standing proof", flash)
        self.assertIn("now refuses a bot short of crypto at 2x", flash)
        self.assertNotIn("still lets", flash)

    def test_a_hold_open_when_its_pair_is_revoked_does_not_reopen_it(self):
        """An overnight hold still held at eToro's demo account when its
        (class, multiplier) is revoked closes clean later: it is recorded,
        revoked with the pair, and announces nothing (the review of
        2026-10-31: it became a fresh 1x proof and reopened the gate)."""
        from django.utils import timezone

        from bot_program import short_proofs
        from bot_program.asset_engine.base import missing_proofs
        from tests.test_switch_pin import TEST_PIN
        wall = timezone.now()
        trip = _proof("crypto", 1, symbol="BTCUSD",
                      at=wall - timedelta(hours=30))
        hold = _proof("crypto", 1, symbol="BTCUSD", state="open",
                      proven=False, overnight=True,
                      at=wall - timedelta(hours=26),
                      hold_until=wall - timedelta(hours=1),
                      close_lookup={"verdict": "clean", "facts": [],
                                    "held_at_fill": {}})
        hold.order_id, hold.position_id = "7001", "900001"
        hold.save(update_fields=["order_id", "position_id"])
        self._revoke(trip, TEST_PIN)
        self.assertEqual(missing_proofs("crypto", "SELL", 1),
                         ["short_crypto"])
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = _run(_demo(wire), wall)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual(len([u for u in wire.urls("POST")
                              if "market-close-orders" in u]), 1)
        hold.refresh_from_db()
        self.assertEqual((hold.proof_state, hold.demo_proven),
                         ("proven", True))
        self.assertIsNotNone(hold.revoked_at)
        self.assertIn("revoked while it was held", hold.revoke_reason)
        self.assertIn("not proven anew", out["did"])
        self.assertEqual(missing_proofs("crypto", "SELL", 1),
                         ["short_crypto"])
        self.notify.assert_not_called()
        steps = {(s["leverage"], s["overnight"]): s["state"]
                 for s in short_proofs.plan(now=wall)
                 if s["asset_class"] == "crypto"}
        self.assertEqual(steps[(1, False)], "revoked")

    def test_a_revoked_overnight_is_measured_again_after_a_fresh_1x(self):
        """The overnight measurement goes with its pair's revoke (its fee
        is read from standing proofs only): once the 1x is proven anew by
        hand, the hold runs again."""
        from bot_program import short_proofs
        from tests.test_switch_pin import TEST_PIN
        trip = _proof("etf", 1)
        _proof("etf", 1, overnight=True, nights=1,
               overnight_fee=Decimal("0.05"), notional=Decimal("80"))
        self._revoke(trip, TEST_PIN)
        self.assertIsNone((short_proofs.measured_short_fees("etf") or {})
                          .get("overnight_fee"))

        def overnight():
            return [s for s in short_proofs.plan(now=MONDAY)
                    if s["asset_class"] == "etf" and s["overnight"]][0]
        self.assertEqual(overnight()["state"], "blocked")
        self.assertIn("after its 1x proof", overnight()["why"])
        _proof("etf", 1)                                  # anew, by hand
        self.assertEqual(overnight()["state"], "due")

    def test_a_wrong_or_missing_pin_revokes_nothing(self):
        from bot_program.audit_models import AuditLogEntry
        from tests.test_switch_pin import WRONG_PIN
        row = _proof("etf", 1)
        for pin in (WRONG_PIN, ""):
            resp = self._revoke(row, pin)
            self.assertEqual(resp.status_code, 302)
            row.refresh_from_db()
            self.assertIsNone(row.revoked_at)
        self.assertFalse(AuditLogEntry.objects.filter(
            kind="short_proof_revoked").exists())

    def test_only_a_superuser_reaches_the_page_and_the_door(self):
        from tests.test_switch_pin import TEST_PIN
        row = _proof("etf", 1)
        self.client.force_login(self.user)          # staff, not superuser
        self.assertEqual(self.client.get("/short-proofs/").status_code, 403)
        self.assertEqual(self._revoke(row, TEST_PIN).status_code, 403)
        row.refresh_from_db()
        self.assertIsNone(row.revoked_at)

    def test_the_page_lists_the_records_and_what_the_bots_may_short(self):
        _proof("etf", 1)
        _proof("crypto", 1, symbol="BTCUSD", state="refused", proven=False,
               refusal="errorCode 749: disallowed for instrument")
        resp = self.client.get("/short-proofs/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("GLDM", body)
        self.assertIn("errorCode 749", body)
        self.assertIn("demo account", body)
        self.assertIn('name="pin"', body)
        self.assertIn("short_proofs_demo", body)

    def test_the_page_prints_plain_numbers(self):
        """A size or a fee prints as written, never in exponent form
        (Decimal.normalize prints 1980 as 1.98E+3)."""
        _proof("index", 1, symbol="SPX500", units=Decimal("1980"),
               fees=Decimal("0.150000"))
        body = self.client.get("/short-proofs/").content.decode()
        self.assertIn(">1980<", body)
        self.assertIn(">0.15<", body)
        self.assertNotIn("E+", body)

    def test_the_brokers_page_and_the_eye_name_a_demo_proof(self):
        from bot_program.telegram_eye import _proof_words
        from dashboard.views_brokers import etoro_proof_states
        before = etoro_proof_states()["short"]
        self.assertEqual(before, "shorts proven on forex, stock only")
        self.assertNotIn("demo account", _proof_words())
        _proof("etf", 1)
        _proof("etf", 2)
        self.assertEqual(etoro_proof_states()["short"],
                         "shorts proven on forex, stock only; on the demo "
                         "account by the platform: etf at 1x, 2x")
        self.assertIn("Short selling (etfs) on the demo account at 1x, 2x",
                      _proof_words())

    def test_clearing_an_in_doubt_stop_lets_the_runner_go_on(self):
        from bot_program import short_proofs
        from bot_program.audit_models import AuditLogEntry
        from tests.test_switch_pin import TEST_PIN
        row = _proof("crypto", 1, symbol="BTCUSD", state="in_doubt",
                     proven=False)
        self.assertIsNotNone(short_proofs.stopped())
        resp = self._revoke(row, TEST_PIN, reason="no position at eToro")
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(short_proofs.stopped())
        self.assertTrue(AuditLogEntry.objects.filter(
            kind="short_proof_cleared").exists())


# ── the switch, the beat and the command ─────────────────────────────────

class TheSwitchTests(_Base):

    def test_the_switch_seeds_on_and_a_reseed_keeps_the_operators_off(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent,
                                           seed_components)
        PlatformComponent.objects.filter(key="short_proofs_demo").delete()
        seed_components()
        row = PlatformComponent.objects.get(key="short_proofs_demo")
        self.assertTrue(row.is_enabled, "it only ever touches the demo "
                                        "account: ON by default")
        self.assertEqual([c["key"] for c in DEFAULT_COMPONENTS
                          if c.get("is_enabled")], ["short_proofs_demo"],
                         "every other switch still arrives OFF")
        row.is_enabled = False
        row.save(update_fields=["is_enabled"])
        seed_components()
        row.refresh_from_db()
        self.assertFalse(row.is_enabled)

    def test_a_class_takes_its_article(self):
        from bot_program import short_proofs
        self.assertEqual([short_proofs.a_class(c) for c in
                          ("etf", "index", "commodity", "crypto")],
                         ["an ETF", "an index", "a commodity", "a crypto"])
        row = _proof("etf", 1, symbol="GLDM", state="in_doubt",
                     proven=False)
        self.assertIn("an ETF short (GLDM) is in doubt",
                      short_proofs.stop_words(row))

    def test_the_texts_say_how_often_and_that_one_switch_arrives_on(self):
        # The beat runs every 15 minutes, but a step waits MIN_GAP_S after
        # the last one: the switch's words give the spacing, not the beat.
        from pathlib import Path

        from django.conf import settings

        from bot_program import short_proofs
        from core.platform_control import DEFAULT_COMPONENTS
        text = next(c for c in DEFAULT_COMPONENTS
                    if c["key"] == "short_proofs_demo")["description"]
        self.assertLessEqual(len(text), 300)
        self.assertIn(f"one step every {short_proofs.MIN_GAP_S // 60} min",
                      text)
        self.assertNotIn("every 15 min, one step", text)
        self.assertIn("DEMO account only", text)
        # /ops/'s empty state named every switch OFF.
        ops = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "ops.html").read_text()
        self.assertNotIn("creates every switch the code knows, OFF.</p>",
                         ops)
        self.assertIn("the demo short proofs alone arrive ON", ops)

    def test_the_task_skips_while_the_switch_is_off(self):
        from bot_program.tasks import run_short_proofs_demo
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="platform_master",
            defaults={"name": "m", "category": "system", "is_enabled": True})
        _switch(False)
        with mock.patch("bot_program.short_proofs.run_once") as run:
            out = run_short_proofs_demo()
        run.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        _switch(True)
        with mock.patch("bot_program.short_proofs.run_once",
                        return_value={"status": "skipped",
                                      "reason": "spaced"}) as run:
            run_short_proofs_demo()
        run.assert_called_once()

    def test_the_task_is_on_the_beat_behind_its_switch(self):
        from config.celery import app
        from core.component_digest import beat_periods
        entries = [e for e in app.conf.beat_schedule.values()
                   if e["task"] == "bot_program.tasks.run_short_proofs_demo"]
        self.assertEqual(len(entries), 1)
        self.assertIn("short_proofs_demo", beat_periods())

    def test_the_command_dry_run_sends_nothing_and_prints_the_plan(self):
        out = StringIO()
        with mock.patch("bot_program.short_proofs.demo_client") as build:
            call_command("short_proofs_demo", "--dry-run", stdout=out)
        build.assert_not_called()
        text = out.getvalue()
        self.assertIn("dry run", text)
        self.assertIn("crypto", text)
        self.assertIn("1x", text)
        self.assertEqual(self._rows(), [])

    def test_the_command_refuses_while_the_switch_is_off(self):
        from django.core.management.base import CommandError
        _switch(False)
        with mock.patch("bot_program.short_proofs.demo_client") as build:
            with self.assertRaises(CommandError) as cm:
                call_command("short_proofs_demo", stdout=StringIO())
        build.assert_not_called()
        self.assertIn("short_proofs_demo", str(cm.exception))

    def test_the_command_runs_one_step(self):
        wire = _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})
        out = StringIO()
        # crypto's market never shuts, so the wall clock is no input here
        with mock.patch("bot_program.short_proofs.demo_client",
                        return_value=_demo(wire)), \
                mock.patch("time.sleep"):
            call_command("short_proofs_demo", "--class", "crypto",
                         stdout=out)
        self.assertEqual(self._rows()[0].proof_state, "proven")
        self.assertIn("proven", out.getvalue())


# ── the overnight measurement ────────────────────────────────────────────

class TheOvernightTests(_Base):
    """GLDM held across New York's close, closed the next session."""

    def _held(self, fees):
        return [{"positionID": 900001, "instrumentID": 3190, "isBuy": False,
                 "units": 1.0, "openRate": 80.0, "leverage": 1,
                 "totalFees": fees, "CID": 9}]

    def test_an_overnight_hold_closes_the_next_session_and_records_its_fee(
            self):
        lookups = {7001: _round_trip(symbol="GLDM", iid=3190, units=1.0,
                                     avg=80.0, fees=0.0)}
        wire = _Wire(rows=[ROW_GLDM], lookups=lookups)
        out = _run(_demo(wire), MONDAY, asset_class="etf", overnight=True)
        self.assertEqual(out["status"], "success", out)
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.overnight, row.demo_proven),
                         ("open", True, False))
        self.assertEqual([u for u in wire.urls("POST")
                          if "market-close-orders" in u], [])
        self.assertGreater(row.hold_until, MONDAY + timedelta(hours=12))
        # the same evening: still held, and no other ETF step meanwhile
        wire = _Wire(rows=[ROW_GLDM], lookups=lookups,
                     portfolio=self._held(0.0))
        out = _run(_demo(wire), MONDAY + timedelta(hours=4),
                   asset_class="etf")
        self.assertEqual(wire.urls("POST"), [])
        # Tuesday, after New York's open: read, then closed
        tuesday = datetime(2026, 11, 3, 15, 30, tzinfo=UTC)
        wire = _Wire(rows=[ROW_GLDM], lookups=lookups,
                     portfolio=self._held(0.05))
        out = _run(_demo(wire), tuesday, asset_class="etf")
        self.assertEqual(out["status"], "success", out)
        self.assertEqual(len([u for u in wire.urls("POST")
                              if "market-close-orders" in u]), 1)
        row.refresh_from_db()
        self.assertEqual((row.proof_state, row.demo_proven, row.nights),
                         ("proven", True, 1))
        self.assertEqual(row.overnight_fee, Decimal("0.05"))
        self.assertNotIn("CID", row.close_lookup.get("held") or {})

    def _hold_then_close(self, held, *, open_fee):
        lookups = {7001: _round_trip(symbol="GLDM", iid=3190, units=1.0,
                                     avg=80.0, fees=open_fee)}
        _run(_demo(_Wire(rows=[ROW_GLDM], lookups=lookups)), MONDAY,
             asset_class="etf", overnight=True)
        tuesday = datetime(2026, 11, 3, 15, 30, tzinfo=UTC)
        out = _run(_demo(_Wire(rows=[ROW_GLDM], lookups=lookups,
                               portfolio=held)), tuesday, asset_class="etf")
        self.assertEqual(out["status"], "success", out)
        [row] = self._rows()
        self.assertEqual((row.proof_state, row.fees),
                         ("proven", Decimal(str(open_fee))))
        return row

    def test_an_overnight_key_is_read_whole(self):
        # A key that names the overnight fee alone is that fee, whole.
        held = self._held(0.0)
        del held[0]["totalFees"]
        held[0]["overnightFees"] = 0.05
        row = self._hold_then_close(held, open_fee=0.02)
        self.assertEqual(row.overnight_fee, Decimal("0.05"))
        self.assertEqual(row.close_lookup["fee_key"], "overnightFees")

    def test_totalfees_is_the_nights_alone_and_is_read_whole(self):
        """MEASURED (tests/test_etoro_client.py PORTFOLIO_ROW, 2026-09-23):
        totalFees printed 0.0 while the open fee, 0.13 (the same order's
        openingData fees), rode totalExternalFees. So totalFees is the
        nights' fee, read whole: taking the open fee off it read -0.13 for
        a position that held no night, and short_fee_fraction then dropped
        the overnight fee (the review of 2026-10-31)."""
        from tests.test_etoro_client import PORTFOLIO_ROW
        self.assertEqual((PORTFOLIO_ROW["totalFees"],
                          PORTFOLIO_ROW["totalExternalFees"]), (0.0, 0.13))
        held = [dict(PORTFOLIO_ROW, positionID=900001, instrumentID=3190,
                     isBuy=False, orderID=7001, totalFees=0.05)]
        row = self._hold_then_close(held, open_fee=0.13)
        self.assertEqual(row.overnight_fee, Decimal("0.05"))
        self.assertEqual(row.close_lookup["fee_key"], "totalFees")
        self.assertNotIn("CID", row.close_lookup["held"])

    def test_the_overnight_runs_once_per_class(self):
        from bot_program import short_proofs
        _proof("etf", 1)
        before = [s for s in short_proofs.plan(now=MONDAY)
                  if s["asset_class"] == "etf" and s["overnight"]]
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["state"], "due")
        _proof("etf", 1, overnight=True, nights=1,
               overnight_fee=Decimal("0.05"))
        after = [s for s in short_proofs.plan(now=MONDAY)
                 if s["asset_class"] == "etf" and s["overnight"]]
        self.assertEqual(after[0]["state"], "done")


# ── the cost of a short ──────────────────────────────────────────────────

class TheShortFeeTests(SimpleTestCase):

    def test_a_measured_short_fee_is_charged_never_less_than_today(self):
        from bot_program.asset_engine.risk_levels import venue_fee_fraction
        fees = {"open_fee": 0.0, "notional": 80.0, "overnight_fee": 0.05,
                "nights": 1, "symbol": "GLDM"}
        self.assertEqual(venue_fee_fraction("etoro", "etf", 1000.0),
                         (0.0, ""), "a BUY, or no measurement: as before")
        fee, words = venue_fee_fraction("etoro", "etf", 1000.0, side="SELL",
                                        short_fees=fees, nights=2)
        self.assertAlmostEqual(fee, 2 * 0.05 / 80.0)
        self.assertIn("demo", words)
        # a measured open fee: the stricter of a flat fee and a share
        fees = {"open_fee": 0.5, "notional": 100.0, "symbol": "GLDM"}
        fee, _ = venue_fee_fraction("etoro", "etf", 1000.0, side="SELL",
                                    short_fees=fees)
        self.assertAlmostEqual(fee, 2 * 0.5 / 100.0)
        fee, _ = venue_fee_fraction("etoro", "etf", 10.0, side="SELL",
                                    short_fees=fees)
        self.assertAlmostEqual(fee, 2 * 0.5 / 10.0)
        # never less than today: crypto's 1% a side stands
        cheap = {"open_fee": 0.01, "notional": 100.0}
        fee, words = venue_fee_fraction("etoro", "crypto", 100.0,
                                        side="SELL", short_fees=cheap)
        self.assertAlmostEqual(fee, 0.02)
        self.assertIn("1%", words)
        # a credit is never a discount
        credit = {"open_fee": 0.0, "notional": 80.0, "overnight_fee": -1.0,
                  "nights": 1}
        self.assertEqual(venue_fee_fraction("etoro", "etf", 80.0,
                                            side="SELL", short_fees=credit),
                         (0.0, ""))


class TheBotsChargeTheMeasuredShortTests(_Base):

    def test_the_fee_refusal_reads_the_measured_short_of_the_class(self):
        from bot_program import short_proofs
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_etoro_client import _client
        from tests.test_execution_trust import _cfg, _instrument
        _instrument("GLDM", "etf")
        bot = StockBot(_cfg(self.user, name="SPF"))
        self.assertIsNone(short_proofs.measured_short_fees("etf"))
        t, _fake = _client([])
        self.assertEqual(bot._venue_fee_refusal(
            t, "GLDM", qty=10, price=80.0, target=70.0, stop=82.0,
            side="SELL"), (0.0, ""))
        _proof("etf", 1, open_rate=Decimal("80"), fees=Decimal("0"),
               notional=Decimal("80"))
        _proof("etf", 1, overnight=True, nights=1,
               overnight_fee=Decimal("0.05"), notional=Decimal("80"),
               open_rate=Decimal("80"), fees=Decimal("0"))
        fees = short_proofs.measured_short_fees("etf")
        self.assertEqual((fees["overnight_fee"], fees["nights"]), (0.05, 1))
        fee, why = bot._venue_fee_refusal(
            t, "GLDM", qty=10, price=80.0, target=70.0, stop=82.0,
            side="SELL", horizon_hours=48)
        self.assertAlmostEqual(fee, 2 * 0.05 / 80.0)
        self.assertEqual(why, "")
        # a long is charged as before
        self.assertEqual(bot._venue_fee_refusal(
            t, "GLDM", qty=10, price=80.0, target=90.0, stop=78.0,
            side="BUY"), (0.0, ""))
