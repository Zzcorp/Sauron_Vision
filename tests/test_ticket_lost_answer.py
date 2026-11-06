"""The ticket whose answer was lost after the PIN (2026-11-06).

A live forex ticket: the operator sent a LIVE order on the manual ticket.
After the PIN the ticket said "Network error", yet the order had gone:
eToro had filled it. Words that read like "nothing happened" after the PIN
invite a second order. What these tests pin:

* THE WORDS. An EXECUTE whose answer is lost (the fetch rejects, or a 5xx
  or an unreadable body comes back: the view may have run behind it) says
  the order MAY have gone and not to send it again. Only a redirect, a 403
  or a 404 (the view never ran) says nothing was sent. A preview's failure
  says nothing was sent; a close whose answer is lost says the close may
  have gone. A 5xx page is never called an expired session.
* THE RECORD. Each send carries a ref the page made (32 lowercase hex).
  The two execute views write "received" before the executor runs and
  "booked" or "refused" once it answers: in the cache, under the user's
  id, for two hours, best-effort. A cache that fails never blocks, alters
  or fails an order, and the executor's arguments and answer are the same
  with or without a ref.
* THE LOOKUP. GET /api/take-trade/outcome/<ref>/ reads the caller's own
  record and nothing else. After a lost answer the ticket asks it a few
  times, with growing gaps, and says what it found.

No broker is ever reached: the executor is patched, or the live leg runs
against the fake client of tests/test_take_trade_live.py. A Redis that
stalls is a loopback port that accepts and never answers. The page's own
JavaScript runs under node with the browser stubbed.

Run with:  python manage.py test tests.test_ticket_lost_answer
"""
import json
import os
import re
import runpy
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock, skipIf

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import (Client, RequestFactory, SimpleTestCase, TestCase,
                         override_settings)
from django.urls import reverse

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _filled_response,
                                        _quote, _signal)

REF = "0123456789abcdef0123456789abcdef"
OTHER_REF = "fedcba9876543210fedcba9876543210"
OUTCOME = "/api/take-trade/outcome/{}/"
ASSET_DOOR = "/instruments/BTCUSD/take-trade/"
SIGNAL_DOOR = "/signals/{}/take-trade/"
EXEC_ASSET = "bot_program.manual_trade.execute_asset_trade"
EXEC_SIGNAL = "bot_program.manual_trade.execute_take_trade"
RECORD_CACHE = "dashboard.ticket_outcome._cache"
RECORD_LOG = "dashboard.ticket_outcome"

#: The executor's words when the broker call raised before its answer
#: arrived, as manual_trade._execute writes them (the live test below runs
#: the real sentence: this copy only drives the record's own tests).
IN_DOUBT_ERROR = ("The live order errored before an answer arrived (read "
                  "timed out). The order MAY have reached the broker — "
                  "check the positions page and the broker before "
                  "retrying")

#: Refs that must be ignored: not exactly 32 lowercase hex characters.
BAD_REFS = ("0123456789ABCDEF0123456789ABCDEF", REF[:31], REF + "0",
            REF + "\n", " " + REF, "g" * 32, "", 12345, 1.5, ["x"],
            {"a": 1}, True)

#: What the execute view answered for a booked LIVE order that the broker
#: holds unfilled, shaped as manual_trade._execute builds it.
BOOKED = {"ok": True, "trade_id": 991, "symbol": "BTCUSD", "side": "BUY",
          "qty": 0.0004, "entry": 60012.5, "stop": 59100.0,
          "target": 61800.0, "risk_dollars": 0.36,
          "sized_by": "risk_budget", "overrides": [], "managed": True,
          "venue": "live", "closed": [], "working": True,
          "protection_note": "The broker accepted the order and has NOT "
                             "filled it — no position is open yet.",
          "readback_note": "eToro holds 2x."}
REFUSED = {"error": "The broker refused the order (insufficient margin) — "
                    "nothing opened", "closed": []}


def _post(client, url, body):
    return client.post(url, data=json.dumps(body),
                       content_type="application/json",
                       HTTP_HOST="127.0.0.1")


def _outcome(client, ref):
    return client.get(OUTCOME.format(ref), HTTP_HOST="127.0.0.1")


def _calls(m):
    """The executor's calls, models by pk and the PIN gate by what it is
    (each request builds a new gate, so identity says nothing)."""
    out = []
    for c in m.call_args_list:
        kw = dict(c.kwargs)
        kw["pin_ok"] = repr(kw.get("pin_ok"))
        out.append((tuple(getattr(a, "pk", a) for a in c.args), kw))
    return out


class _Boom:
    """A cache whose every call fails."""

    def __getattr__(self, name):
        def fail(*a, **k):
            raise RuntimeError("tl boom")
        return fail


class _Timed:
    """A cache whose calls are timed: (name, seconds) for each, kept in
    `spent`, whether it answered or raised."""

    def __init__(self, inner):
        self.inner, self.spent = inner, []

    def __getattr__(self, name):
        call = getattr(self.inner, name)

        def timed(*a, **k):
            t0 = time.monotonic()
            try:
                return call(*a, **k)
            finally:
                self.spent.append((name, time.monotonic() - t0))
        return timed


@contextmanager
def _silent_server():
    """A loopback port that accepts connections and never answers a byte:
    a Redis that stalls. Yields its redis:// URL."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    stop, held = threading.Event(), []

    def accept():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            held.append(conn)

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        yield f"redis://127.0.0.1:{srv.getsockname()[1]}/0"
    finally:
        stop.set()
        t.join(2)
        srv.close()
        for conn in held:
            conn.close()


def _production_caches():
    """config/settings.py's CACHES as production builds them (DEBUG off:
    Redis is taken as given, no probe), evaluated apart from the settings
    this run uses."""
    env = {"DEBUG": "False", "REDIS_URL": "redis://127.0.0.1:6399/0",
           "SENTRY_DSN": ""}
    with mock.patch.dict(os.environ, env):
        conf = runpy.run_path(
            str(Path(settings.BASE_DIR) / "config" / "settings.py"))
    return conf["CACHES"]


# ── the body ────────────────────────────────────────────────────────────
class TheRefIsReadStrictlyTests(SimpleTestCase):
    """_parse_trade_body carries the ref, or None: a bad ref is never an
    error, so it can never refuse an order."""

    def _parse(self, body):
        from dashboard.views import _parse_trade_body
        req = RequestFactory().post("/x", data=json.dumps(body),
                                    content_type="application/json")
        return _parse_trade_body(req)

    def test_a_good_ref_is_carried(self):
        out, err = self._parse({"side": "BUY", "ticket_ref": REF})
        self.assertIsNone(err)
        self.assertEqual(out["ticket_ref"], REF)

    def test_anything_else_is_none_and_never_an_error(self):
        base, err = self._parse({"side": "BUY"})
        self.assertIsNone(err)
        self.assertIsNone(base["ticket_ref"])
        for bad in BAD_REFS:
            with self.subTest(ref=bad):
                out, err = self._parse({"side": "BUY", "ticket_ref": bad})
                self.assertIsNone(err)
                self.assertEqual(out, base)

    def test_the_rule_is_one_function(self):
        from dashboard.ticket_outcome import clean_ref
        self.assertEqual(clean_ref(REF), REF)
        for bad in BAD_REFS + (None,):
            with self.subTest(ref=bad):
                self.assertIsNone(clean_ref(bad))


# ── the record around the executor ──────────────────────────────────────
class TheRecordAroundTheExecutorTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tl_u", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        self.client.force_login(self.user)

    def _doors(self):
        """Both execute views: (name, url, the executor's patch target, the
        body a plain send carries there)."""
        sig = _signal(self.inst)
        return (("asset", ASSET_DOOR, EXEC_ASSET, {"side": "BUY"}),
                ("signal", SIGNAL_DOOR.format(sig.id), EXEC_SIGNAL, {}))

    def test_received_is_written_before_the_executor_runs(self):
        from dashboard import ticket_outcome
        seen = {}

        def executor(user, inst, side, close_ids, **kw):
            seen["during"] = ticket_outcome.read(user.pk, REF)
            return dict(BOOKED)

        with mock.patch(EXEC_ASSET, side_effect=executor):
            r = _post(self.client, ASSET_DOOR,
                      {"side": "BUY", "ticket_ref": REF})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(seen["during"]["state"], "received")
        self.assertTrue(seen["during"].get("at"))
        self.assertEqual(_outcome(self.client, REF).json()["state"],
                         "booked")

    def test_the_signal_door_records_the_same_way(self):
        from dashboard import ticket_outcome
        sig = _signal(self.inst)
        seen = {}

        def executor(user, signal, close_ids, **kw):
            seen["during"] = ticket_outcome.read(user.pk, REF)
            return dict(REFUSED)

        with mock.patch(EXEC_SIGNAL, side_effect=executor):
            r = _post(self.client, f"/signals/{sig.id}/take-trade/",
                      {"ticket_ref": REF})
        self.assertEqual(r.json(), REFUSED)
        self.assertEqual(seen["during"]["state"], "received")
        out = _outcome(self.client, REF).json()
        self.assertEqual(out["state"], "refused")
        self.assertEqual(out["error"], REFUSED["error"])

    def test_a_booked_order_is_recorded_with_what_its_answer_carried(self):
        with mock.patch(EXEC_ASSET, return_value=dict(BOOKED)):
            _post(self.client, ASSET_DOOR, {"side": "BUY", "ticket_ref": REF})
        out = _outcome(self.client, REF).json()
        self.assertEqual(out["state"], "booked")
        for key in ("trade_id", "symbol", "side", "qty", "entry", "venue",
                    "working", "protection_note", "readback_note"):
            with self.subTest(key=key):
                self.assertEqual(out[key], BOOKED[key])

    def test_the_record_is_the_users_own_and_lives_two_hours(self):
        from dashboard import ticket_outcome
        self.assertEqual(ticket_outcome.TTL_SECONDS, 2 * 3600)
        spy = mock.MagicMock(wraps=cache)
        with mock.patch(EXEC_ASSET, return_value=dict(BOOKED)), \
                mock.patch(RECORD_CACHE, return_value=spy):
            _post(self.client, ASSET_DOOR, {"side": "BUY", "ticket_ref": REF})
        writes = spy.add.call_args_list + spy.set.call_args_list
        self.assertEqual(len(writes), 2)       # received, then booked
        for c in writes:
            self.assertEqual(c.args[0], f"ticket_ref:{self.user.pk}:{REF}")
            ttl = c.args[2] if len(c.args) > 2 else c.kwargs.get("timeout")
            self.assertEqual(ttl, 2 * 3600)

    def test_a_ref_that_is_not_32_lowercase_hex_is_ignored(self):
        for door, url, path, base in self._doors():
            with self.subTest(door=door):
                cache.clear()
                spy = mock.MagicMock(wraps=cache)
                with mock.patch(path, return_value=dict(BOOKED)) as ex, \
                        mock.patch(RECORD_CACHE, return_value=spy):
                    plain = _post(self.client, url, base)
                    for bad in BAD_REFS:
                        with self.subTest(door=door, ref=bad):
                            r = _post(self.client, url,
                                      dict(base, ticket_ref=bad))
                            self.assertEqual(r.status_code, 200)
                            self.assertEqual(r.content, plain.content)
                spy.add.assert_not_called()
                spy.set.assert_not_called()
                calls = _calls(ex)
                self.assertEqual(len(calls), 1 + len(BAD_REFS))
                for c in calls[1:]:
                    self.assertEqual(c, calls[0])

    def test_the_ref_changes_neither_the_executors_arguments_nor_the_answer(
            self):
        for door, url, path, base in self._doors():
            with self.subTest(door=door):
                cache.clear()
                body = dict(base, pin="1234", qty=0.5, leverage=2)
                with mock.patch(path, return_value=dict(BOOKED)) as ex:
                    plain = _post(self.client, url, body)
                    with_ref = _post(self.client, url,
                                     dict(body, ticket_ref=OTHER_REF))
                self.assertEqual(plain.content, with_ref.content)
                self.assertEqual(json.loads(with_ref.content), BOOKED)
                self.assertNotIn(OTHER_REF, with_ref.content.decode())
                a, b = _calls(ex)
                self.assertEqual(a, b)
                self.assertNotIn("ticket_ref", b[1])

    def test_a_cache_that_fails_never_blocks_or_changes_the_order(self):
        for broken in ({"side_effect": RuntimeError("tl boom")},
                       {"return_value": _Boom()}):
            with self.subTest(broken=sorted(broken)):
                cache.clear()
                with mock.patch(EXEC_ASSET, return_value=dict(BOOKED)) as ex:
                    plain = _post(self.client, ASSET_DOOR, {"side": "BUY"})
                    with mock.patch(RECORD_CACHE, **broken):
                        r = _post(self.client, ASSET_DOOR,
                                  {"side": "BUY", "ticket_ref": REF})
                        lookup = _outcome(self.client, REF)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.content, plain.content)
                self.assertNotIn("tl boom", r.content.decode())
                a, b = _calls(ex)
                self.assertEqual(a, b)
                # an unreadable record is a failed read, never "unknown"
                self.assertEqual(lookup.status_code, 503)
                self.assertNotIn("state", lookup.json())
                self.assertNotIn("tl boom", lookup.content.decode())

    def test_a_real_paper_order_books_when_the_record_fails(self):
        from bot_program.models import AssetBotTrade
        sig = _signal(self.inst)
        with mock.patch(RECORD_CACHE, side_effect=RuntimeError("tl boom")):
            r = _post(self.client, f"/signals/{sig.id}/take-trade/",
                      {"ticket_ref": REF})
        self.assertTrue(r.json().get("ok"), r.json())
        self.assertEqual(AssetBotTrade.objects.filter(
            config__user=self.user, status="OPEN").count(), 1)

    def test_a_real_paper_order_reads_booked(self):
        sig = _signal(self.inst)
        r = _post(self.client, f"/signals/{sig.id}/take-trade/",
                  {"ticket_ref": REF})
        res = r.json()
        self.assertTrue(res.get("ok"), res)
        out = _outcome(self.client, REF).json()
        self.assertEqual(out["state"], "booked")
        self.assertEqual(out["trade_id"], res["trade_id"])
        self.assertEqual(out["venue"], "paper")

    def test_an_executor_that_raises_leaves_received(self):
        """A 500 after the order may have left: the record never claims a
        refusal nobody saw."""
        client = Client(raise_request_exception=False)
        client.force_login(self.user)
        for door, url, path, base in self._doors():
            with self.subTest(door=door):
                cache.clear()
                with mock.patch(path, side_effect=RuntimeError("after")), \
                        self.assertLogs("django.request", level="ERROR"):
                    r = _post(client, url, dict(base, ticket_ref=REF))
                self.assertEqual(r.status_code, 500)
                self.assertEqual(_outcome(client, REF).json()["state"],
                                 "received")

    def test_a_second_send_of_the_same_ref_never_rewrites_the_first(self):
        """A browser that replays a POST sends the same body twice: the
        replay's refusal ("already in flight", "already taken") is not
        what became of the order."""
        for door, url, path, base in self._doors():
            with self.subTest(door=door):
                cache.clear()
                with mock.patch(path, side_effect=[
                        dict(BOOKED),
                        {"error": "An identical LIVE order is already in "
                                  "flight"}]) as ex:
                    _post(self.client, url, dict(base, ticket_ref=REF))
                    again = _post(self.client, url,
                                  dict(base, ticket_ref=REF))
                self.assertEqual(ex.call_count, 2)      # never refused by it
                self.assertIn("already in flight", again.json()["error"])
                self.assertEqual(_outcome(self.client, REF).json()["state"],
                                 "booked")

    def test_a_result_that_cannot_be_written_never_touches_the_order(self):
        """'received' is written, then the result's write fails: by then
        the order is at the broker, so the answer reaches the page whole,
        the executor ran as without a ref, the failure is logged by its
        type, and the record stays 'received' (review, 2026-11-06)."""
        from dashboard import ticket_outcome
        for door, url, path, base in self._doors():
            for name, answer in (("booked", BOOKED), ("refused", REFUSED)):
                with self.subTest(door=door, answer=name):
                    cache.clear()
                    spy = mock.MagicMock(wraps=ticket_outcome._cache())
                    spy.set.side_effect = RuntimeError("tl boom")
                    with mock.patch(path, return_value=dict(answer)) as ex:
                        plain = _post(self.client, url, base)
                        with mock.patch(RECORD_CACHE, return_value=spy), \
                                self.assertLogs(RECORD_LOG,
                                                "WARNING") as logs:
                            r = _post(self.client, url,
                                      dict(base, ticket_ref=REF))
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(r.content, plain.content)
                    a, b = _calls(ex)
                    self.assertEqual(a, b)
                    spy.add.assert_called_once()
                    spy.set.assert_called_once()
                    self.assertEqual(
                        _outcome(self.client, REF).json()["state"],
                        "received")
                    said = " ".join(logs.output)
                    self.assertIn("RuntimeError", said)
                    self.assertNotIn("tl boom", said)

    def test_a_record_keeps_the_funding_closes_and_the_levels(self):
        for name, answer, keys in (
                ("booked", dict(BOOKED, closed=[3]),
                 ("stop", "target", "closed")),
                ("refused", dict(REFUSED, closed=[3, 4]), ("closed",))):
            with self.subTest(answer=name):
                cache.clear()
                with mock.patch(EXEC_ASSET, return_value=answer):
                    _post(self.client, ASSET_DOOR,
                          {"side": "BUY", "ticket_ref": REF})
                out = _outcome(self.client, REF).json()
                self.assertEqual(out["state"], name)
                for key in keys:
                    self.assertEqual(out[key], answer[key])

    def test_an_answer_in_doubt_is_recorded_apart_from_a_refusal(self):
        """'The order MAY have reached the broker' is no refusal: the
        record says in_doubt, so the page never has to match the
        executor's sentence to keep "nothing opened" off it (review,
        2026-11-06). The answer itself reaches the page untouched."""
        for name, answer, doubt in (
                ("in doubt", {"error": IN_DOUBT_ERROR}, True),
                ("refused", dict(REFUSED), False)):
            with self.subTest(answer=name):
                cache.clear()
                with mock.patch(EXEC_ASSET, return_value=dict(answer)):
                    r = _post(self.client, ASSET_DOOR,
                              {"side": "BUY", "ticket_ref": REF})
                self.assertEqual(r.json(), answer)
                out = _outcome(self.client, REF).json()
                self.assertEqual(out["state"], "refused")
                self.assertEqual(out["error"], answer["error"])
                self.assertIs(out["in_doubt"], doubt)


# ── the lookup door ─────────────────────────────────────────────────────
class TheOutcomeDoorTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user("tl_door", password="x")
        cls.other = User.objects.create_user("tl_other", password="x")

    def setUp(self):
        cache.clear()
        _quote("BTCUSD", 60000)
        self.client.force_login(self.user)

    def test_its_url(self):
        self.assertEqual(reverse("take_trade_outcome", args=[REF]),
                         OUTCOME.format(REF))

    def test_unknown_when_nothing_was_recorded(self):
        r = _outcome(self.client, OTHER_REF)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"state": "unknown"})

    def test_only_the_callers_own_record_is_read(self):
        with mock.patch(EXEC_ASSET, return_value=dict(BOOKED)):
            _post(self.client, ASSET_DOOR, {"side": "BUY", "ticket_ref": REF})
        theirs = Client()
        theirs.force_login(self.other)
        self.assertEqual(_outcome(theirs, REF).json(), {"state": "unknown"})
        self.assertEqual(_outcome(self.client, REF).json()["state"],
                         "booked")

    def test_get_only(self):
        for method in ("post", "put", "delete", "patch"):
            with self.subTest(method=method):
                r = getattr(self.client, method)(OUTCOME.format(REF),
                                                 HTTP_HOST="127.0.0.1")
                self.assertEqual(r.status_code, 405)

    def test_login_required(self):
        r = Client().get(OUTCOME.format(REF), HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/wall/", r["Location"])

    def test_a_malformed_ref_reads_unknown_without_touching_the_cache(self):
        spy = mock.MagicMock(wraps=cache)
        with mock.patch(RECORD_CACHE, return_value=spy):
            for bad in ("ABC", REF.upper(), REF[:31], "g" * 32):
                with self.subTest(ref=bad):
                    r = _outcome(self.client, bad)
                    self.assertEqual(r.json(), {"state": "unknown"})
        self.assertEqual(spy.method_calls, [])

    def test_never_cached(self):
        r = _outcome(self.client, REF)
        self.assertIn("no-store", r["Cache-Control"])

    def test_it_lives_under_api_so_a_locked_tab_is_answered_423(self):
        s = self.client.session
        s["pin_locked"] = True
        s.save()
        r = _outcome(self.client, REF)
        self.assertEqual(r.status_code, 423)
        s = self.client.session
        s["pin_locked"] = False
        s.save()
        r = _outcome(self.client, REF)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"state": "unknown"})

    def test_it_asks_no_broker_and_runs_no_executor(self):
        with mock.patch(ROUTER) as router, \
                mock.patch(EXEC_ASSET) as ex, mock.patch(EXEC_SIGNAL) as sx:
            r = _outcome(self.client, REF)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"state": "unknown"})
        router.assert_not_called()
        ex.assert_not_called()
        sx.assert_not_called()


# ── the record's own cache: a store that stalls costs a send little ─────
class TheRecordsOwnCacheTests(TestCase):
    """The record is written just before a send and just after it. On the
    default cache a Redis that stalls (accepts, never answers) held the
    send 5 s each way, redis-py's default socket timeout (review,
    2026-11-06). The record writes through its own alias instead: the same
    store, with timeouts under a second."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tl_fuse",
                                                        password="x")

    def setUp(self):
        cache.clear()
        _quote("BTCUSD", 60000)
        self.client.force_login(self.user)

    def test_it_writes_through_its_own_alias(self):
        from dashboard import ticket_outcome
        self.assertIn(ticket_outcome.CACHE_ALIAS, settings.CACHES)
        self.assertIs(ticket_outcome._cache(),
                      caches[ticket_outcome.CACHE_ALIAS])

    def test_it_is_the_same_store_as_the_default(self):
        from dashboard import ticket_outcome
        ticket_outcome._cache().set("tl:probe", 7, 30)
        self.assertEqual(cache.get("tl:probe"), 7)

    def test_settings_without_the_alias_write_through_the_default(self):
        from dashboard import ticket_outcome
        with override_settings(CACHES={"default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "tl-no-alias"}}):
            self.assertIs(ticket_outcome._cache(), caches["default"])

    def test_in_production_it_is_the_same_redis_with_a_short_fuse(self):
        from dashboard import ticket_outcome
        conf = _production_caches()
        alias = conf[ticket_outcome.CACHE_ALIAS]
        self.assertEqual(alias["BACKEND"],
                         "django.core.cache.backends.redis.RedisCache")
        self.assertEqual(alias["LOCATION"], conf["default"]["LOCATION"])
        self.assertLessEqual(alias["OPTIONS"]["socket_timeout"], 1.0)
        self.assertLessEqual(alias["OPTIONS"]["socket_connect_timeout"], 1.0)
        # the default cache itself is left as it was
        self.assertNotIn("OPTIONS", conf["default"])

    def test_a_stalled_store_holds_a_send_well_under_the_old_5_s(self):
        """Each of the record's calls gives up in about half a second.
        MEASURED 2026-11-06 against this port: 0.56 s through this alias
        (0.66 s on a machine at load 13 on 4 cores), 5.0 to 6.2 s through
        the default one, whose timeout is a floor no machine runs under.
        Timed around the cache calls themselves, not the whole request,
        whose own cost a loaded machine stretches."""
        from django.core.cache.backends.redis import RedisCache
        from dashboard import ticket_outcome
        alias = _production_caches()[ticket_outcome.CACHE_ALIAS]
        params = {k: v for k, v in alias.items()
                  if k not in ("BACKEND", "LOCATION")}
        with _silent_server() as url:
            stalled = _Timed(RedisCache(url, params))
            with mock.patch(EXEC_ASSET, return_value=dict(BOOKED)) as ex, \
                    mock.patch(RECORD_CACHE, return_value=stalled), \
                    self.assertLogs(RECORD_LOG, "WARNING"):
                r = _post(self.client, ASSET_DOOR,
                          {"side": "BUY", "ticket_ref": REF})
                lookup = _outcome(self.client, REF)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), BOOKED)
        ex.assert_called_once()
        # an unreadable record is a failed read, never "unknown"
        self.assertEqual(lookup.status_code, 503)
        self.assertNotIn("state", lookup.json())
        # 'received' failed, so no result was written; the lookup read once
        self.assertEqual([name for name, _ in stalled.spent], ["add", "get"])
        for name, spent in stalled.spent:
            with self.subTest(call=name):
                self.assertLess(spent, 2.0)


# ── the live leg, end to end, on a fake broker ──────────────────────────
class TheLiveTicketIsRecordedTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from portfolio.trader_profile import get_or_create_profile
        cls.user = get_user_model().objects.create_user("tl_live",
                                                        password="x")
        prof = get_or_create_profile(cls.user)
        prof.set_pin("4321")
        prof.save()

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        self.client.force_login(self.user)

    def test_a_filled_live_order_reads_booked_and_live(self):
        broker = _fake_live_client()
        with mock.patch(ROUTER, return_value=broker):
            out = _post(self.client, ASSET_DOOR,
                        {"side": "BUY", "pin": "4321",
                         "ticket_ref": REF}).json()
        self.assertTrue(out.get("ok"), out)
        broker.market_order.assert_called_once()
        rec = _outcome(self.client, REF).json()
        self.assertEqual(rec["state"], "booked")
        self.assertEqual(rec["venue"], "live")
        for key in ("trade_id", "symbol", "side", "qty", "entry"):
            with self.subTest(key=key):
                self.assertEqual(rec[key], out[key])

    def test_an_error_after_the_order_left_is_a_500_that_reads_received(
            self):
        """The case this module was written for: the broker took the order,
        then the view died before it answered. The page saw a 500; the
        record says the order reached Sauron and has no final answer, never
        that it was refused."""
        client = Client(raise_request_exception=False)
        client.force_login(self.user)
        broker = _fake_live_client()
        with mock.patch(ROUTER, return_value=broker), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           ".venue_stamps",
                           side_effect=RuntimeError("tl after the send")), \
                self.assertLogs("django.request", level="ERROR"):
            r = _post(client, ASSET_DOOR,
                      {"side": "BUY", "pin": "4321", "ticket_ref": REF})
        self.assertEqual(r.status_code, 500)
        broker.market_order.assert_called_once()
        self.assertEqual(_outcome(client, REF).json()["state"], "received")

    def test_a_wrong_pin_reads_refused_and_nothing_was_sent(self):
        broker = _fake_live_client()
        with mock.patch(ROUTER, return_value=broker):
            out = _post(self.client, ASSET_DOOR,
                        {"side": "BUY", "pin": "9999",
                         "ticket_ref": REF}).json()
        self.assertIn("PIN", out["error"])
        broker.market_order.assert_not_called()
        rec = _outcome(self.client, REF).json()
        self.assertEqual(rec["state"], "refused")
        self.assertEqual(rec["error"], out["error"])     # the PIN's words

    def test_the_fifth_wrong_pin_is_recorded_under_the_user_it_signed_out(
            self):
        from dashboard import ticket_outcome
        from tests.test_switch_pin import _set_count
        session = self.client.session
        _set_count(session, 4)
        broker = _fake_live_client()
        with mock.patch(ROUTER, return_value=broker):
            out = _post(self.client, ASSET_DOOR,
                        {"side": "BUY", "pin": "9999",
                         "ticket_ref": REF}).json()
        self.assertIs(out.get("logged_out"), True, out)
        broker.market_order.assert_not_called()
        rec = ticket_outcome.read(self.user.pk, REF)
        self.assertEqual(rec["state"], "refused")
        self.assertEqual(rec["error"], out["error"])

    def test_a_broker_call_that_raises_reads_in_doubt_on_the_page_and_record(
            self):
        """The executor's own sentence when the broker call raised before
        its answer arrived, on the real live leg: the page's pattern reads
        it in the answer, and the record flags it in doubt. A rewording of
        that sentence fails here, instead of telling an order that may
        have filled "Trade not taken" or "Nothing opened" (review,
        2026-11-06)."""
        broker = _fake_live_client()
        broker.market_order.side_effect = TimeoutError("read timed out")
        with mock.patch(ROUTER, return_value=broker), \
                self.assertLogs("bot_program.manual_trade", level="ERROR"):
            out = _post(self.client, ASSET_DOOR,
                        {"side": "BUY", "pin": "4321",
                         "ticket_ref": REF}).json()
        broker.market_order.assert_called_once()
        self.assertNotIn("ok", out)
        page = _page_in_doubt()
        self.assertRegex(out["error"], page)
        rec = _outcome(self.client, REF).json()
        self.assertEqual(rec["state"], "refused")
        self.assertIs(rec["in_doubt"], True)
        self.assertEqual(rec["error"], out["error"])
        self.assertRegex(rec["error"], page)

    def test_a_refusal_from_the_broker_is_recorded_as_one(self):
        broker = _fake_live_client(_filled_response(
            status="REJECTED", executedQty="0", avgPrice="0",
            refusal="insufficient margin"))
        with mock.patch(ROUTER, return_value=broker):
            out = _post(self.client, ASSET_DOOR,
                        {"side": "BUY", "pin": "4321",
                         "ticket_ref": REF}).json()
        broker.market_order.assert_called_once()
        self.assertIn("insufficient margin", out["error"])
        self.assertIn("nothing opened", out["error"])
        self.assertNotRegex(out["error"], _page_in_doubt())
        rec = _outcome(self.client, REF).json()
        self.assertEqual(rec["state"], "refused")
        self.assertIs(rec["in_doubt"], False)
        self.assertEqual(rec["error"], out["error"])


# ── the page's words, read from its source ──────────────────────────────
def _base():
    return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")


TICKET_START = "/* ── TAKE TRADE — a signal proposes, the operator disposes"
TICKET_END = "/* ── A TELEGRAM BUTTON'S PAGE (2026-10-24)"


def _ticket_source():
    src = _base()
    i = src.index(TICKET_START)
    return src[i:src.index(TICKET_END, i)]


def _page_in_doubt():
    """The page's own in-doubt pattern (base.html, mayHaveReached), as a
    Python regex: its literal is plain words."""
    m = re.search(r"function mayHaveReached\(text\) \{\s*"
                  r"return /([^/]+)/([a-z]*)\.test\(", _ticket_source())
    assert m, "mayHaveReached is not in the ticket's script"
    return re.compile(m.group(1), re.I if "i" in m.group(2) else 0)


#: The gaps between the asks, as the page schedules them.
GAPS = [1000, 3000, 6000, 12000, 20000, 30000]


def _ask_ms():
    """How long one ask may hang before the page cuts it (OUTCOME_ASK_MS);
    10000 when the page names none, so the harness still runs."""
    m = re.search(r"var OUTCOME_ASK_MS = (\d+);", _ticket_source())
    return int(m.group(1)) if m else 10000


class TheTicketSourceTests(SimpleTestCase):

    def test_no_bare_network_error_is_left(self):
        self.assertNotIn("'Network error'", _ticket_source())

    def test_a_page_with_html_in_it_is_not_an_expired_session(self):
        """Only a redirect is a login. A 5xx page carries <html too."""
        self.assertNotIn("indexOf('<html')", _ticket_source())

    def test_the_execute_answer_is_read_apart_from_the_previews(self):
        src = _ticket_source()
        flow = src[src.index("function tradeFlow("):]
        preview = flow.index(".then(", flow.index("fetch(previewUrl, {"))
        self.assertTrue(flow.startswith(".then(decode)", preview))
        execute = flow.index(".then(", flow.index("fetch(executeUrl, {"))
        self.assertTrue(flow.startswith(".then(decodeSent)", execute))
        close = src[src.index("function closeFlow(btn)"):]
        sent = close.index(".then(", close.index("'/close/', {"))
        self.assertTrue(close.startswith(".then(decodeCloseSent)", sent))

    def test_each_send_carries_its_own_ref(self):
        src = _ticket_source()
        flow = src[src.index("function tradeFlow("):
                   src.index("window.svTakeTrade = function")]
        chosen = flow.index("sizeDialog(p).then")
        relever = flow.index("if (choice.relever)")
        made = flow.index("var ref = ticketRef();")
        carried = flow.index("body.ticket_ref = ref;")
        sent = flow.index("fetch(executeUrl")
        self.assertLess(chosen, relever)
        self.assertLess(relever, made)    # a new multiplier sends nothing
        self.assertLess(made, carried)
        self.assertLess(carried, sent)
        self.assertIn("crypto.getRandomValues", src)

    def test_the_lookup_asks_the_outcome_door_with_growing_gaps(self):
        src = _ticket_source()
        self.assertIn("var OUTCOME_URL = '/api/take-trade/outcome/';", src)
        self.assertIn("var OUTCOME_GAPS = [1000, 3000, 6000, 12000, 20000, "
                      "30000];", src)
        ask = src[src.index("function askOutcome("):]
        ask = ask[:ask.index("\n  }\n")]
        self.assertIn("'Accept': 'application/json'", ask)
        self.assertIn("method: 'GET'", ask)

    def test_each_ask_is_cut_after_a_bounded_wait(self):
        """A hung ask must end (review, 2026-11-06). The harness below
        tells an ask's cut from a gap by its length, so it is none of
        them."""
        m = re.search(r"var OUTCOME_ASK_MS = (\d+);", _ticket_source())
        self.assertIsNotNone(m)
        ms = int(m.group(1))
        self.assertGreaterEqual(ms, 3000)
        self.assertLessEqual(ms, 15000)
        self.assertNotIn(ms, GAPS)


# ── the page's JavaScript, run under node ───────────────────────────────
_NODE = shutil.which("node")

PRELUDE = r"""
const realST = setTimeout, realCT = clearTimeout;
const ASK_MS = __ASK_MS__;
const L = {};
let route = () => Promise.reject(new Error('no route'));
let HOLD = false;
const held = [];
function reset() {
  L.alerts = []; L.events = []; L.fetches = []; L.delays = [];
  L.opened = []; L.assigned = []; L.dismissed = [];
  L.refreshes = 0; L.counts = 0; L.cuts = 0; L.screens = [];
}
reset();
globalThis.setTimeout = (fn, ms) => {
  /* An ask's own cut (OUTCOME_ASK_MS) is no gap between asks: it runs on
     the next turn, after an ask that settles has cleared it, so only an
     ask that hangs meets it. */
  if (ms === ASK_MS) { L.cuts += 1; return realST(fn, 0); }
  if (ms >= 1000) {
    L.delays.push(ms);
    if (HOLD) { const t = { fn: fn, cancelled: false }; held.push(t); return t; }
  }
  return realST(fn, 0);
};
globalThis.clearTimeout = (t) => {
  if (t && typeof t === 'object' && 'cancelled' in t) t.cancelled = true;
  else realCT(t);
};
function fireHeld() {
  held.splice(0).forEach((t) => { if (!t.cancelled) t.fn(); });
}
function fakeEl(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(), className: '', style: {},
    hidden: false, disabled: false, textContent: '', parentNode: null,
    attrs: {}, on: {}, roles: {}, _html: '',
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    removeAttribute(k) { delete this.attrs[k]; },
    addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); },
    fire(t) { (this.on[t] || []).slice().forEach((f) => f({ type: t, target: this })); },
    appendChild(c) { c.parentNode = this; return c; },
    removeChild(c) { c.parentNode = null; return c; },
    closest() { return null; },
    focus() {},
    querySelector(sel) {
      const m = /data-role="([^"]+)"/.exec(sel);
      if (!m || this._html.indexOf('data-role="' + m[1] + '"') === -1) return null;
      if (!this.roles[m[1]]) this.roles[m[1]] = fakeEl('node');
      return this.roles[m[1]];
    },
    querySelectorAll() { return []; },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(h) { el._html = String(h); el.roles = {}; },
  });
  return el;
}
globalThis.document = {
  cookie: 'csrftoken=t', body: fakeEl('body'),
  createElement: (t) => fakeEl(t),
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: (ev) => { L.events.push(ev.type); return true; },
};
globalThis.window = globalThis;
globalThis.location = { assign: (u) => L.assigned.push(u) };
globalThis.svLiveRefresh = () => { L.refreshes += 1; };
globalThis.refreshPanelCounts = () => { L.counts += 1; };
globalThis.dismissSignal = (id) => { L.dismissed.push(String(id)); };
globalThis.SV = { overlay: {
  alert: (o) => { L.alerts.push({ title: String(o.title), message: String(o.message || '') }); return Promise.resolve(true); },
  confirm: () => Promise.resolve('4321'),
  open: (h) => { L.opened.push(h); },
  close: (h) => { h.fire('sv:close'); },
} };
globalThis.__sizeDialog = () => Promise.resolve({
  qty: null, stop: null, target: null, close_ids: [], pin: '4321',
  leverage: null, dup_seen: [] });
globalThis.fetch = (url, init) => {
  init = init || {};
  L.fetches.push({ url: String(url), method: init.method || 'GET',
                   headers: init.headers || {}, body: init.body,
                   signal: init.signal || null });
  return route(String(url), init);
};
function answer(status, body, opt) {
  opt = opt || {};
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return Promise.resolve({
    status: status, ok: status >= 200 && status < 300,
    redirected: !!opt.redirected, url: opt.url || '',
    headers: { get: (k) => /content-type/i.test(k)
      ? (typeof body === 'string' ? 'text/html' : 'application/json') : null },
    text: () => Promise.resolve(text),
    json: () => { try { return Promise.resolve(JSON.parse(text)); }
                  catch (e) { return Promise.reject(e); } },
  });
}
const dropped = () => Promise.reject(new TypeError('Failed to fetch'));
/* a half-open line: the ask never settles */
const hang = () => new Promise(() => {});
const HTML500 = '<!doctype html><html lang="en"><body><h1>Server Error (500)</h1></body></html>';
const HTML_PAGE = '<!doctype html><html><body>a page</body></html>';
const PREVIEW = { symbol: 'EURJPY', side: 'BUY', qty: 2000, entry: 168.4,
                  stop: 167.9, target: 169.4, venue: 'live', requires_pin: true };
const BOOKED = { state: 'booked', trade_id: 5, symbol: 'EURJPY', side: 'BUY',
                 qty: 2000, entry: 168.412, venue: 'live', working: false };
const RECEIVED = { state: 'received', at: '2026-11-06T09:00:00+00:00' };
const MAY = 'The live order errored before an answer arrived (read timed out). The order MAY have reached the broker — check the positions page and the broker before retrying';
const tick = () => new Promise((r) => realST(r, 5));
async function until(cond, what) {
  for (let i = 0; i < 3000; i++) {
    if (cond()) return;
    await new Promise((r) => realST(r, 1));
  }
  throw new Error('timed out waiting for ' + what);
}
function txt(h, role) { const n = h && h.roles[role]; return n ? String(n.textContent || '') : ''; }
function dialog() {
  for (let i = L.opened.length - 1; i >= 0; i--) {
    if ((L.opened[i]._html || '').indexOf('data-role="outcome-title"') !== -1) return L.opened[i];
  }
  return null;
}
function screen() {
  const h = dialog();
  return h ? { title: txt(h, 'outcome-title'), msg: txt(h, 'outcome-msg'),
               step: txt(h, 'outcome-step'), why: txt(h, 'outcome-why'),
               outcome: h.getAttribute('data-outcome') } : null;
}
function previews() { return L.fetches.filter((x) => x.url.indexOf('/preview/') !== -1).length; }
function polls() { return L.fetches.filter((x) => x.url.indexOf('/api/take-trade/outcome/') === 0); }
function summary() {
  /* a copy: what was on screen when the answer settled, before any probe */
  return JSON.parse(JSON.stringify({
    alerts: L.alerts, events: L.events, refreshes: L.refreshes, counts: L.counts,
    sent: L.fetches.filter((x) => /\/take-trade\/$/.test(x.url))
                   .map((x) => JSON.parse(x.body)),
    polls: polls().map((p) => ({ url: p.url, method: p.method,
                                 accept: (p.headers || {})['Accept'] || null,
                                 aborted: !!(p.signal && p.signal.aborted) })),
    delays: L.delays, screen: screen(), dismissed: L.dismissed,
    assigned: L.assigned, screens: L.screens, cuts: L.cuts,
    persist: dialog() ? dialog().hasAttribute('data-sv-persist') : null,
  }));
}
async function released() {
  const before = previews(), saved = route;
  route = (url) => url.indexOf('/preview/') !== -1
    ? answer(200, { error: 'probe' }) : Promise.reject(new Error('unexpected ' + url));
  window.svTakeTradeAsset('EURJPY', 'BUY');
  for (let i = 0; i < 10; i++) await tick();
  route = saved;
  return previews() > before;
}
async function ticket(execute, asked, opts) {
  opts = opts || {};
  reset();
  let n = 0;
  route = (url) => {
    if (url.indexOf('/take-trade/preview/') !== -1) return opts.preview ? opts.preview() : answer(200, PREVIEW);
    if (url.indexOf('/api/take-trade/outcome/') === 0) {
      L.screens.push(screen());   /* what was on screen as this ask went out */
      const a = asked[Math.min(n, asked.length - 1)]; n += 1;
      return typeof a === 'function' ? a() : answer(200, a);
    }
    if (/\/take-trade\/$/.test(url)) return execute();
    return Promise.reject(new Error('unexpected ' + url));
  };
  if (opts.signal) window.svTakeTrade(7); else window.svTakeTradeAsset('EURJPY', 'BUY');
  await until(() => L.alerts.length > 0 || (dialog() && dialog().getAttribute('data-outcome')),
              'an answer');
  for (let i = 0; i < 5; i++) await tick();
  const out = summary();
  if (dialog()) SV.overlay.close(dialog());
  out.released = await released();
  return out;
}
async function closeIt(execute, preview) {
  reset();
  route = (url) => {
    if (/\/close\/preview\/$/.test(url)) return preview ? preview() : answer(200,
      { side: 'BUY', qty: 2000, symbol: 'EURJPY', entry: 168.4, mark: 168.5,
        exit: 168.5, pnl: 1.3, r: 0.2, venue: 'live' });
    if (/\/close\/$/.test(url)) return execute();
    return Promise.reject(new Error('unexpected ' + url));
  };
  window.svCloseTrade(42);
  await until(() => L.alerts.length > 0, 'the close answer');
  for (let i = 0; i < 5; i++) await tick();
  return summary();
}
function out(x) { process.stdout.write(JSON.stringify(x)); }
function fail(e) { console.error(String(e && e.stack || e)); process.exit(1); }
"""


def _ticket_iife():
    """The page's TAKE TRADE and CLOSE script, its size dialog stubbed: the
    stub resolves the operator's choice; everything else is the page's."""
    iife = _ticket_source()
    assert "{%" not in iife and "{{" not in iife
    stub = ("function sizeDialog(p) { return globalThis.__sizeDialog(p); }\n"
            "  function __pageSizeDialog(p) {")
    return iife.replace("function sizeDialog(p) {", stub, 1)


def _run(scenario):
    script = (PRELUDE.replace("__ASK_MS__", str(_ask_ms())) + _ticket_iife()
              + "\n" + scenario)
    with tempfile.TemporaryDirectory(prefix="sv-ticketnet-") as tmp:
        path = os.path.join(tmp, "case.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        proc = subprocess.run([_NODE, path], capture_output=True, text=True,
                              timeout=120)
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr[:1500]}")
    return json.loads(proc.stdout)


def _titles(s):
    return [a["title"] for a in s["alerts"]]


def _said(s):
    """Everything the page put in front of the operator."""
    bits = [a["title"] + " " + a["message"] for a in s["alerts"]]
    if s.get("screen"):
        bits.append(" ".join(str(v) for v in s["screen"].values()))
    return " | ".join(bits)


#: The one sentence allowed to say nothing was sent while the outcome is
#: unknown: a condition on the line having dropped BEFORE the order left.
ALLOWED_IF = ("If the line dropped before the order left this page, "
              "nothing was sent")
NOTHING_SENT = re.compile(
    r"nothing (?:was|has been) sent|was not sent|nothing reached", re.I)

#: Words that claim the broker has not answered. 'received' only means no
#: result was written: eToro may have filled the order already.
BROKER_SILENT = re.compile(
    r"broker has not answered|broker hasn't answered|from the broker", re.I)


def _claims_nothing_was_sent(text):
    """Any claim that nothing went, in any phrasing, once the one allowed
    condition ("If the line dropped before the order left this page,
    nothing was sent") is taken out."""
    return NOTHING_SENT.search(text.replace(ALLOWED_IF, ""))


def _every_screen(s):
    """One text per thing the operator saw: the dialog as it stood when
    each ask went out, the dialog at the end, and every alert."""
    out = [" ".join(str(v) for v in sc.values())
           for sc in (s.get("screens") or []) if sc]
    if s.get("screen"):
        out.append(" ".join(str(v) for v in s["screen"].values()))
    out += [a["title"] + " " + a["message"] for a in s["alerts"]]
    return out


#: A redirect the idle lock answers a POST with (core/idle_lock): a POST
#: that asks for no JSON is sent to /locked/, never answered 423.
LOCKED_TICKET = ("() => answer(200, HTML_PAGE, { redirected: true, url: "
                 "'http://127.0.0.1/locked/?next=%2Finstruments%2FEURUSD"
                 "%2Ftake-trade%2F' })")
LOCKED_CLOSE = ("() => answer(200, HTML_PAGE, { redirected: true, url: "
                "'http://127.0.0.1/locked/?next=%2Fpositions%2F42%2Fclose%2F' })")


@skipIf(_NODE is None, "node is not installed")
class TheTicketTellsTheTruthTests(TestCase):
    """The ticket's own script, under node: what the operator reads after
    the PIN, for every way the answer can come back or not."""

    def assertMayHaveGoneFirst(self, s):
        self.assertNotIn("Network error", _titles(s))
        self.assertNotIn("Session expired", _said(s))
        self.assertNotIn("Trade not taken", _titles(s))

    def assertAskedTheDoor(self, s, n):
        ref = s["sent"][0]["ticket_ref"]
        self.assertRegex(ref, r"^[0-9a-f]{32}$")
        self.assertEqual(len(s["polls"]), n)
        for p in s["polls"]:
            self.assertEqual(p["url"], f"/api/take-trade/outcome/{ref}/")
            self.assertEqual(p["method"], "GET")
            self.assertEqual(p["accept"], "application/json")
        return ref

    def test_a_dropped_line_after_the_pin_is_looked_up_and_names_the_order(
            self):
        s = _run("ticket(dropped, [RECEIVED, BOOKED]).then(out, fail);")
        self.assertMayHaveGoneFirst(s)
        self.assertEqual(s["alerts"], [])     # one dialog carries it all
        self.assertAskedTheDoor(s, 2)
        self.assertEqual(s["delays"][:2], [1000, 3000])
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "booked")
        self.assertIn("went", scr["title"].lower())
        for bit in ("BUY", "2000", "EURJPY", "168.412", "LIVE"):
            self.assertIn(bit, scr["msg"])
        self.assertIn("Failed to fetch", scr["why"])
        # the positions are asked again: when the line drops and when the
        # booked row is found
        self.assertGreaterEqual(s["events"].count("sv:position-changed"), 2)
        self.assertGreaterEqual(s["refreshes"], 1)
        self.assertGreaterEqual(s["counts"], 1)
        self.assertIs(s["released"], True)

    def assertEToroFirst(self, msg):
        """The words that send the operator to check: the eToro app first,
        since Sauron's Positions may not show an order it holds no row for
        (a 500 after the send: eToro filled it, the view died before the
        row)."""
        self.assertIn("check the eToro app first", msg)
        self.assertIn("Positions may not show it", msg)
        self.assertIn("then Positions", msg)

    def assertNeverSaysNothingWasSent(self, s):
        for text in _every_screen(s):
            self.assertIsNone(_claims_nothing_was_sent(text), text)

    def test_a_5xx_is_never_an_expired_session_and_received_says_wait(self):
        s = _run("ticket(() => answer(502, HTML500), [RECEIVED])"
                 ".then(out, fail);")
        self.assertMayHaveGoneFirst(s)
        self.assertAskedTheDoor(s, 6)
        self.assertEqual(s["delays"][:6],
                         [1000, 3000, 6000, 12000, 20000, 30000])
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "received")
        self.assertIn("no final answer", scr["title"].lower())
        self.assertIn("Do not send it again", scr["msg"])
        # re-pinned (review, 2026-11-06): the eToro app first, then
        # Positions, where these words named "Positions and the eToro app"
        self.assertEToroFirst(scr["msg"])
        self.assertIn("502", scr["why"])
        self.assertNeverSaysNothingWasSent(s)
        self.assertIs(s["released"], True)

    def test_received_never_says_the_broker_has_not_answered(self):
        """Review, 2026-11-06: when eToro has filled the order and the view
        dies before it books the row, the record reads 'received' — no
        result was written, which says nothing about the broker. Neither
        the asking nor the last words may say the broker has not
        answered."""
        s = _run("ticket(() => answer(500, HTML500), [RECEIVED])"
                 ".then(out, fail);")
        self.assertAskedTheDoor(s, 6)
        self.assertEqual(s["screen"]["outcome"], "received")
        texts = _every_screen(s)
        self.assertEqual(len(texts), 7)      # as each of 6 asks left, and last
        for text in texts:
            self.assertIsNone(BROKER_SILENT.search(text), text)
        self.assertIn("no result is recorded for it yet",
                      s["screens"][1]["step"])
        scr = s["screen"]
        self.assertIn("no result recorded", scr["msg"])
        self.assertIn("may still be working", scr["msg"])
        self.assertIn("Do not send it again", scr["msg"])
        self.assertEToroFirst(scr["msg"])
        self.assertNeverSaysNothingWasSent(s)

    def test_no_record_never_claims_nothing_was_sent(self):
        s = _run("ticket(() => answer(500, HTML500), [{ state: 'unknown' }])"
                 ".then(out, fail);")
        self.assertMayHaveGoneFirst(s)
        self.assertAskedTheDoor(s, 6)
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "unknown")
        self.assertIn("no record", scr["msg"].lower())
        # re-pinned as above: the eToro app first, then Positions
        self.assertEToroFirst(scr["msg"])
        self.assertIsNone(_claims_nothing_was_sent(_said(s)), _said(s))
        self.assertIn(ALLOWED_IF, scr["msg"])   # the condition, kept whole
        self.assertNeverSaysNothingWasSent(s)

    def test_an_unreadable_answer_is_looked_up_too(self):
        for name, execute in (("empty 504", "() => answer(504, '')"),
                              ("json without a verdict",
                               "() => answer(200, {})"),
                              ("a page", "() => answer(200, HTML_PAGE)"),
                              # any 5xx, JSON or not: the view may have run
                              ("json 500",
                               "() => answer(500, { error: 'boom' })")):
            with self.subTest(name=name):
                s = _run(f"ticket({execute}, [BOOKED]).then(out, fail);")
                self.assertMayHaveGoneFirst(s)
                self.assertAskedTheDoor(s, 1)
                self.assertEqual(s["screen"]["outcome"], "booked")

    def test_a_refusal_found_by_the_lookup_says_nothing_opened(self):
        s = _run("ticket(dropped, [{ state: 'refused', error: 'The broker "
                 "refused the order (insufficient margin) — nothing opened',"
                 " closed: [] }]).then(out, fail);")
        self.assertAskedTheDoor(s, 1)
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "refused")
        self.assertIn("refused", scr["title"].lower())
        self.assertIn("nothing opened", scr["title"].lower())
        self.assertIn("insufficient margin", scr["msg"])
        self.assertIn("Nothing opened", scr["msg"])

    def test_a_lookup_that_finds_may_have_reached_never_says_nothing_opened(
            self):
        s = _run("ticket(dropped, [{ state: 'refused', error: MAY }])"
                 ".then(out, fail);")
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "refused")
        self.assertIn("may have reached the broker", scr["title"].lower())
        self.assertIn("MAY have reached the broker", scr["msg"])
        self.assertNotIn("nothing opened", _said(s).lower())
        self.assertGreaterEqual(s["events"].count("sv:position-changed"), 2)

    def test_a_record_in_doubt_reads_may_have_reached_whatever_its_words(
            self):
        """The record flags it (in_doubt), so these words never hang on the
        page matching the executor's sentence (review, 2026-11-06)."""
        s = _run("ticket(dropped, [{ state: 'refused', in_doubt: true, "
                 "error: 'The live order errored before an answer arrived "
                 "(read timed out).', closed: [] }]).then(out, fail);")
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "refused")
        self.assertIn("may have reached the broker", scr["title"].lower())
        self.assertIn("read timed out", scr["msg"])
        self.assertNotIn("nothing opened", _said(s).lower())
        self.assertEToroFirst(scr["msg"])

    def test_polls_that_fail_keep_the_may_have_gone_words(self):
        s = _run("ticket(dropped, [dropped]).then(out, fail);")
        self.assertMayHaveGoneFirst(s)
        self.assertEqual(len(s["polls"]), 6)
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "unanswered")
        self.assertIn("may have gone", scr["title"].lower())
        self.assertIn("could not be asked", scr["msg"])
        # re-pinned as above: the eToro app first, then Positions
        self.assertEToroFirst(scr["msg"])
        self.assertIsNone(_claims_nothing_was_sent(_said(s)), _said(s))
        self.assertNeverSaysNothingWasSent(s)

    def test_a_hung_ask_is_cut_and_the_asks_carry_on_to_their_last_words(
            self):
        """Review, 2026-11-06: an ask on a half-open line that never
        settled stalled the asks on "asking again…" for good, with no last
        words. Each ask is cut after OUTCOME_ASK_MS, counted as an ask
        that failed, and the asks go on."""
        s = _run("ticket(dropped, [hang, RECEIVED]).then(out, fail);")
        self.assertMayHaveGoneFirst(s)
        self.assertAskedTheDoor(s, 6)
        self.assertEqual(s["delays"][:6], GAPS)
        self.assertEqual(s["screen"]["outcome"], "received")
        self.assertEqual([p["aborted"] for p in s["polls"]],
                         [True] + [False] * 5)
        self.assertEqual(s["cuts"], 6)              # one per ask
        self.assertIs(s["released"], True)
        s = _run("ticket(dropped, [hang]).then(out, fail);")
        self.assertAskedTheDoor(s, 6)
        self.assertEqual(s["delays"][:6], GAPS)
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "unanswered")
        self.assertIn("could not be asked", scr["msg"])
        self.assertEqual([p["aborted"] for p in s["polls"]], [True] * 6)
        self.assertNeverSaysNothingWasSent(s)
        self.assertIs(s["released"], True)

    def test_the_answer_stays_up_until_the_operator_closes_it(self):
        """Escape or a stray tap outside must not end the asking: the
        dialog reports something the operator must act on
        (data-sv-persist); its X and its button still close it."""
        s = _run("ticket(dropped, [BOOKED]).then(out, fail);")
        self.assertIs(s["persist"], True)
        self.assertIs(s["released"], True)

    def test_a_working_order_found_booked_is_not_called_open(self):
        s = _run("ticket(dropped, [Object.assign({}, BOOKED, { symbol: "
                 "'EURUSD', working: true, protection_note: 'The broker "
                 "accepted the order and has NOT filled it — no position is "
                 "open yet.', readback_note: 'eToro holds 2x.', closed: [3] "
                 "})]).then(out, fail);")
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "booked")
        self.assertIn("not filled yet", scr["title"])
        self.assertNotIn("position open", scr["title"].lower())
        self.assertNotIn("168.412", scr["msg"])   # no entry: nothing filled
        for bit in ("BUY", "2000", "EURUSD", "LIVE", "has NOT filled it",
                    "eToro holds 2x.", "closed first: 3"):
            with self.subTest(bit=bit):
                self.assertIn(bit, scr["msg"])

    def test_a_paper_order_found_booked_is_not_called_live(self):
        s = _run("ticket(dropped, [Object.assign({}, BOOKED, "
                 "{ venue: 'paper' })]).then(out, fail);")
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "booked")
        self.assertIn("168.412", scr["msg"])
        self.assertNotIn("LIVE", scr["msg"])

    def test_a_refusal_found_names_the_funding_closes_already_made(self):
        s = _run("ticket(dropped, [{ state: 'refused', error: 'The broker "
                 "refused the order (insufficient margin) — nothing opened',"
                 " closed: [3, 4] }]).then(out, fail);")
        scr = s["screen"]
        self.assertEqual(scr["outcome"], "refused")
        self.assertIn("Already closed for funding: 3, 4", scr["msg"])

    def test_a_failed_or_locked_poll_never_erases_what_was_found(self):
        s = _run("ticket(dropped, ["
                 "() => answer(423, { pin_locked: true }), "
                 "() => answer(200, HTML_PAGE, { redirected: true }), "
                 "RECEIVED, { state: 'unknown' }, dropped, "
                 "() => answer(503, { error: 'unreadable' })])"
                 ".then(out, fail);")
        self.assertEqual(len(s["polls"]), 6)
        self.assertEqual(s["screen"]["outcome"], "received")

    def test_closing_the_answer_stops_the_lookup_and_frees_the_ticket(self):
        s = _run(r"""
(async () => {
  reset();
  HOLD = true;
  let n = 0;
  route = (url) => {
    if (url.indexOf('/preview/') !== -1) return answer(200, PREVIEW);
    if (url.indexOf('/api/take-trade/outcome/') === 0) { n += 1; return answer(200, RECEIVED); }
    if (/\/take-trade\/$/.test(url)) return dropped();
    return Promise.reject(new Error('unexpected ' + url));
  };
  window.svTakeTradeAsset('EURJPY', 'BUY');
  await until(() => dialog() && held.length === 1, 'the first ask scheduled');
  const checking = screen();
  fireHeld();
  await until(() => n === 1 && held.length === 1, 'the second ask scheduled');
  for (let i = 0; i < 5; i++) await tick();
  const before = previews();
  window.svTakeTradeAsset('EURJPY', 'BUY');      // a second click meanwhile
  for (let i = 0; i < 10; i++) await tick();
  const heldBack = previews() === before;
  SV.overlay.close(dialog());
  fireHeld();
  for (let i = 0; i < 10; i++) await tick();
  const asked = n;
  HOLD = false;
  const rel = await released();
  out({ checking, heldBack, asked, released: rel });
})().catch(fail);
""")
        self.assertIn("may have gone", s["checking"]["title"].lower())
        self.assertIn("do not send it again", s["checking"]["msg"].lower())
        self.assertIs(s["heldBack"], True)   # the guard holds while unsure
        self.assertEqual(s["asked"], 1)      # closing ended the lookup
        self.assertIs(s["released"], True)   # ...and freed the ticket

    def test_the_signal_card_retires_when_the_lookup_finds_it_booked(self):
        s = _run("ticket(dropped, [BOOKED], { signal: true })"
                 ".then(out, fail);")
        self.assertEqual(s["screen"]["outcome"], "booked")
        self.assertEqual(s["dismissed"], ["7"])

    def test_each_attempt_carries_a_new_ref(self):
        s = _run(r"""
(async () => {
  const a = await ticket(dropped, [BOOKED]);
  const b = await ticket(dropped, [BOOKED]);
  out({ a: a.sent[0].ticket_ref, b: b.sent[0].ticket_ref });
})().catch(fail);
""")
        self.assertRegex(s["a"], r"^[0-9a-f]{32}$")
        self.assertRegex(s["b"], r"^[0-9a-f]{32}$")
        self.assertNotEqual(s["a"], s["b"])

    def test_a_ref_is_made_without_crypto_too(self):
        s = _run(r"""
(async () => {
  Object.defineProperty(globalThis, 'crypto', { value: undefined, configurable: true });
  const a = await ticket(dropped, [BOOKED]);
  out({ a: a.sent[0].ticket_ref });
})().catch(fail);
""")
        self.assertRegex(s["a"], r"^[0-9a-f]{32}$")

    # ── answers that DID come back ──────────────────────────────────────
    def test_a_refusal_in_the_answer_is_trade_not_taken_and_asks_nothing(
            self):
        s = _run("ticket(() => answer(200, { error: 'This signal is already "
                 "taken — position #3 (BUY EURJPY) is open' }), [BOOKED])"
                 ".then(out, fail);")
        self.assertEqual(_titles(s), ["Trade not taken"])
        self.assertIn("already taken", s["alerts"][0]["message"])
        self.assertEqual(s["polls"], [])
        self.assertIs(s["released"], True)

    def test_may_have_reached_in_the_answer_is_not_trade_not_taken(self):
        s = _run("ticket(() => answer(200, { error: MAY }), [BOOKED])"
                 ".then(out, fail);")
        self.assertNotIn("Trade not taken", _titles(s))
        self.assertEqual(len(s["alerts"]), 1)
        self.assertIn("may have reached the broker",
                      s["alerts"][0]["title"].lower())
        self.assertIn("MAY have reached the broker",
                      s["alerts"][0]["message"])
        self.assertIn("sv:position-changed", s["events"])
        self.assertEqual(s["polls"], [])

    def test_only_a_redirect_a_403_or_a_404_says_nothing_was_sent(self):
        for name, execute, words in (
                ("login", "() => answer(200, HTML_PAGE, { redirected: true })",
                 "Session expired"),
                ("csrf", "() => answer(403, HTML_PAGE)", "Not allowed"),
                ("gone", "() => answer(404, HTML_PAGE)", "no longer active")):
            with self.subTest(name=name):
                s = _run(f"ticket({execute}, [BOOKED]).then(out, fail);")
                self.assertEqual(_titles(s), ["Trade not taken"])
                msg = s["alerts"][0]["message"]
                self.assertIn(words, msg)
                self.assertIn("Nothing was sent", msg)
                self.assertEqual(s["polls"], [])
                self.assertIs(s["released"], True)
        s = _run("ticket(() => answer(404, HTML_PAGE), [BOOKED])"
                 ".then(out, fail);")
        self.assertIn("instrument", s["alerts"][0]["message"])  # both doors

    def test_a_locked_screen_says_unlock_it_and_that_nothing_was_sent(self):
        """The idle lock answers the ticket's POSTs with a redirect to
        /locked/ (they ask for no JSON), in front of the view: nothing was
        sent, and the remedy is the PIN, not a new login (review,
        2026-11-06)."""
        s = _run(f"ticket({LOCKED_TICKET}, [BOOKED]).then(out, fail);")
        self.assertEqual(_titles(s), ["Trade not taken"])
        msg = s["alerts"][0]["message"]
        self.assertIn("screen is locked", msg)
        self.assertIn("PIN", msg)
        self.assertIn("Nothing was sent", msg)
        self.assertNotIn("Session expired", msg)
        self.assertEqual(s["polls"], [])
        self.assertIs(s["released"], True)
        c = _run(f"closeIt({LOCKED_CLOSE}).then(out, fail);")
        self.assertEqual(_titles(c), ["Position not closed"])
        msg = c["alerts"][0]["message"]
        self.assertIn("screen is locked", msg)
        self.assertIn("Nothing was closed", msg)
        self.assertNotIn("Session expired", msg)

    def test_a_filled_answer_is_still_position_open(self):
        s = _run("ticket(() => answer(200, { ok: true, trade_id: 5, "
                 "symbol: 'EURJPY', side: 'BUY', qty: 2000, entry: 168.4, "
                 "stop: 167.9, target: 169.4, venue: 'live', closed: [] }), "
                 "[BOOKED]).then(out, fail);")
        self.assertEqual(_titles(s), ["Position open"])
        self.assertIn("sv:position-changed", s["events"])
        self.assertEqual(s["polls"], [])

    def test_a_session_ended_by_the_pin_still_goes_to_the_wall(self):
        s = _run("ticket(() => answer(200, { error: 'PIN', pin_required: "
                 "true, logged_out: true }), [BOOKED]).then(out, fail);")
        self.assertEqual(_titles(s), ["Trade not taken"])
        self.assertEqual(s["assigned"], ["/wall/"])

    # ── the preview ─────────────────────────────────────────────────────
    def test_a_preview_that_fails_says_nothing_was_sent(self):
        for name, preview in (("dropped", "dropped"),
                              ("502", "() => answer(502, HTML500)"),
                              ("500", "() => answer(500, HTML500)")):
            with self.subTest(name=name):
                s = _run(f"ticket(dropped, [BOOKED], {{ preview: {preview} }})"
                         ".then(out, fail);")
                self.assertNotIn("Network error", _titles(s))
                self.assertNotIn("Session expired", _said(s))
                self.assertIn("Nothing was sent", _said(s))
                self.assertEqual(s["sent"], [])
                self.assertEqual(s["polls"], [])
                self.assertIs(s["released"], True)

    # ── the close ───────────────────────────────────────────────────────
    def test_a_close_whose_answer_is_lost_may_have_gone(self):
        for name, execute in (("dropped", "dropped"),
                              ("502", "() => answer(502, '')"),
                              ("500", "() => answer(500, HTML500)")):
            with self.subTest(name=name):
                s = _run(f"closeIt({execute}).then(out, fail);")
                self.assertEqual(len(s["alerts"]), 1)
                a = s["alerts"][0]
                self.assertNotEqual(a["title"], "Network error")
                self.assertNotIn("Session expired", a["message"])
                self.assertIn("may have gone", a["title"].lower())
                self.assertIn("check Positions before closing it again",
                              a["message"])
                self.assertIn("sv:position-changed", s["events"])
                self.assertGreaterEqual(s["refreshes"], 1)
                self.assertEqual(s["polls"], [])     # no lookup for a close

    def test_a_close_that_never_left_says_nothing_was_closed(self):
        for name, execute, preview, title in (
                ("preview dropped", "dropped", "dropped",
                 "Could not reach the platform"),
                ("gone", "() => answer(404, HTML_PAGE)", "null",
                 "Position not closed"),
                ("login", "() => answer(200, HTML_PAGE, { redirected: true })",
                 "null", "Position not closed")):
            with self.subTest(name=name):
                s = _run(f"closeIt({execute}, {preview}).then(out, fail);")
                self.assertEqual(_titles(s), [title])
                self.assertIn("Nothing was closed", s["alerts"][0]["message"])

    def test_a_closed_answer_is_still_position_closed(self):
        s = _run("closeIt(() => answer(200, { ok: true, side: 'BUY', qty: 2000,"
                 " symbol: 'EURJPY', exit: 168.5, pnl: 1.3, r: 0.2 }))"
                 ".then(out, fail);")
        self.assertEqual(_titles(s), ["Position closed"])
