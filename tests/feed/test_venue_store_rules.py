"""THE FEED'S STORES AND THEIR WRITE RULES, W1-W7 ON BOTH IMPLEMENTATIONS
(the eToro feed spec, F1, §5.2-§5.3; 2026-11-07).

market_data.venue_store keeps eToro's quotes per channel — vq:ws:{iid} for
the stream, vq:rest:{iid} for the feed's REST reads — and every write is a
compare-and-set by eToro's own Date: a Redis Lua script in production and
an in-memory twin with the same rules for tests and replay. The same table
of frames runs through both and must leave both stores byte for byte
alike. What is pinned:

  W1  a missing side, a value <= 0, a non-finite or unparsable value, a
      crossed quote, a spread above 10% of the mid: refused and counted,
      nothing stored;
  W2  a newer Date replaces, confirmed at its arrival;
  W3  the same Date and sides, or the same rate id: a confirmation only
      (a REST answer confirms at its arrival less C_rest);
  W4  the same Date with other sides: kept as stored, counted;
  W5  an older Date never replaces; an older snapshot confirms nothing;
  W6  a price-less frame is liveness only;
  W7  a REST answer without a Date is kept beside the record, for display;
  and "0", eToro's no-price word, never replaces a priced record: the
  absence is noted beside it and never refreshes its confirmation.

Also: the read-time choice (current), the key names, the Lua script's
refusal of any key outside vq:*, and the read-only view of the engine's
rates cache (etoro_rates:r:*), which nothing here ever writes.

The Redis half runs only where a redis-server binary is installed (it is
started on a private unix socket in a temporary folder and stopped after);
elsewhere it is skipped and the twin's half still runs. Run with:
    python manage.py test tests.feed.test_venue_store_rules
"""
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock, skipUnless

from django.test import SimpleTestCase

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=dt_tz.utc)
REDIS_SERVER = shutil.which("redis-server")


def _vs():
    from market_data import venue_store
    return venue_store


def _at(seconds):
    return NOW + timedelta(seconds=seconds)


def _frame(kind, bid="1.1000", ask="1.1002", *, vt=0, arrival=1,
           rate_id="", **kw):
    """A frame of `kind` whose eToro Date is NOW + vt s, arriving at
    NOW + arrival s."""
    vs = _vs()
    return vs.frame(kind=kind, bid=bid, ask=ask,
                    vt=None if vt is None else _at(vt), rate_id=rate_id,
                    arrival=_at(arrival), **kw)


class _Rules:
    """The table, run against `self.store` (set by the subclass)."""

    IID = 7

    def _w(self, channel, fr):
        return self.store.write(self.IID, channel, fr)

    def test_w1_refusals_are_counted_and_store_nothing(self):
        vs = _vs()
        for reason, (bid, ask) in {"missing_side": ("1.1000", None),
                                   "not_positive": ("-1", "1.1002"),
                                   "not_finite": ("NaN", "1.1002"),
                                   "unparsed": ("x", "1.1002"),
                                   "crossed": ("1.1004", "1.1002"),
                                   "wide_spread": ("1", "2")}.items():
            with self.subTest(reason=reason):
                fr = _frame("push", bid, ask)
                self.assertEqual(fr.outcome_hint, vs.REFUSED)
                self.assertEqual(fr.reason, reason)
                self.assertEqual(self._w("ws", fr), vs.REFUSED)
                self.assertIsNone(self.store.record(self.IID, "ws"))
        self.assertEqual(self.store.counts["refused"], 6)
        self.assertEqual(self.store.counts["refused:crossed"], 1)

    def test_w2_newer_replaces_confirmed_at_arrival(self):
        vs = _vs()
        self.assertEqual(self._w("ws", _frame("push", vt=0, arrival=1)),
                         vs.NEW)
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=2, arrival=3)), vs.NEW)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.ask), (Decimal("1.1001"),
                                          Decimal("1.1003")))
        self.assertEqual(q.vt, _at(2))
        self.assertEqual(q.confirmed_at, _at(3))
        self.assertEqual(q.channel, "ws")

    def test_w3_same_is_a_confirmation_only(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1, rate_id="r1"))
        self.assertEqual(self._w("ws", _frame("push", vt=0, arrival=5)),
                         vs.SAME)
        q = self.store.record(self.IID, "ws")
        self.assertEqual(q.confirmed_at, _at(5))
        self.assertEqual(q.arrival, _at(1), "the record itself is kept")
        # the same rate id, whatever the sides: the same print
        self.assertEqual(self._w("ws", _frame("snapshot", "1.2", "1.2002",
                                              vt=0, arrival=9,
                                              rate_id="r1")), vs.SAME)
        self.assertEqual(self.store.record(self.IID, "ws").bid,
                         Decimal("1.1000"))

    def test_w3_a_rest_answer_confirms_at_arrival_less_c_rest(self):
        vs = _vs()
        self._w("rest", _frame("rest", vt=0, arrival=1, c_rest_s=60))
        self.assertEqual(self.store.record(self.IID, "rest").confirmed_at,
                         _at(1 - 60))
        self.assertEqual(self._w("rest", _frame("rest", vt=0, arrival=100,
                                                c_rest_s=60)), vs.SAME)
        self.assertEqual(self.store.record(self.IID, "rest").confirmed_at,
                         _at(40))
        # an earlier confirmation never moves it back
        self._w("rest", _frame("rest", vt=0, arrival=50, c_rest_s=60))
        self.assertEqual(self.store.record(self.IID, "rest").confirmed_at,
                         _at(40))

    def test_w4_a_conflict_keeps_the_stored_sides_and_is_counted(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1))
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=0, arrival=2)),
                         vs.CONFLICT)
        q = self.store.record(self.IID, "ws")
        self.assertEqual(q.bid, Decimal("1.1000"))
        self.assertEqual(q.confirmed_at, _at(1), "a conflict confirms nothing")
        self.assertEqual(self.store.counts["same_ts_conflict"], 1)

    def test_w5_older_never_replaces_and_an_older_snapshot_confirms_nothing(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=10, arrival=11))
        self.assertEqual(self._w("ws", _frame("push", "1.2000", "1.2002",
                                              vt=5, arrival=12)), vs.OLDER)
        self.assertEqual(self._w("ws", _frame("snapshot", "1.2000", "1.2002",
                                              vt=5, arrival=13)),
                         vs.SNAPSHOT_OLDER)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.vt, q.confirmed_at),
                         (Decimal("1.1000"), _at(10), _at(11)))
        self.assertEqual(self.store.counts["snapshot_older"], 1)
        self.assertEqual(self.store.counts["older"], 1)

    def test_w6_a_priceless_frame_is_liveness_only(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1))
        fr = _frame("push", None, None, vt=30, arrival=30)
        self.assertEqual(fr.outcome_hint, vs.PRICELESS)
        self.assertEqual(self._w("ws", fr), vs.PRICELESS)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.vt, q.confirmed_at), (_at(0), _at(1)))
        self.assertEqual(self.store.raw(self.IID, "ws")["seen"],
                         str(int(_at(30).timestamp() * 1000)))

    def test_w7_an_untimed_rest_answer_is_kept_beside_for_display(self):
        vs = _vs()
        self._w("rest", _frame("rest", vt=0, arrival=1))
        fr = _frame("rest", "1.3000", "1.3002", vt=None, arrival=40)
        self.assertEqual(fr.outcome_hint, vs.UNTIMED)
        self.assertEqual(self._w("rest", fr), vs.UNTIMED)
        q = self.store.record(self.IID, "rest")
        self.assertEqual(q.bid, Decimal("1.1000"), "never the record")
        raw = self.store.raw(self.IID, "rest")
        self.assertEqual((raw["ub"], raw["ua"]), ("1.3000", "1.3002"))
        # with no record yet, an untimed answer still makes none
        self.store.write(99, "rest", fr)
        self.assertIsNone(self.store.record(99, "rest"))

    def test_a_zero_never_replaces_a_priced_record(self):
        vs = _vs()
        self._w("rest", _frame("rest", vt=0, arrival=1))
        for bid, ask in (("0", "0"), ("0", None), (None, None)):
            with self.subTest(bid=bid, ask=ask):
                fr = _frame("rest", bid, ask, vt=20, arrival=20)
                self.assertEqual(fr.outcome_hint, vs.ZERO)
                self.assertEqual(self._w("rest", fr), vs.ZERO)
        q = self.store.record(self.IID, "rest")
        self.assertEqual((q.bid, q.vt), (Decimal("1.1000"), _at(0)))
        self.assertEqual(q.confirmed_at, _at(1 - 60),
                         "an absence never refreshes the confirmation")
        raw = self.store.raw(self.IID, "rest")
        self.assertEqual(raw["absent_n"], "3")
        self.assertEqual(raw["absent"], str(int(_at(20).timestamp() * 1000)))

    def test_a_newer_priced_answer_after_an_absence_replaces(self):
        vs = _vs()
        self._w("rest", _frame("rest", "0", "0", vt=0, arrival=1))
        self.assertIsNone(self.store.record(self.IID, "rest"))
        self.assertEqual(self._w("rest", _frame("rest", vt=5, arrival=6)),
                         vs.NEW)
        self.assertEqual(self.store.raw(self.IID, "rest")["absent"], "")

    def test_the_channels_never_mix(self):
        """I2: each channel writes only its own key."""
        self._w("ws", _frame("push", vt=0, arrival=1))
        self.assertIsNone(self.store.record(self.IID, "rest"))
        self._w("rest", _frame("rest", "1.1005", "1.1007", vt=9,
                               arrival=10))
        self.assertEqual(self.store.record(self.IID, "ws").bid,
                         Decimal("1.1000"))

    def test_current_until_cross_channel_dates_are_proven(self):
        """Until M2 proves the Dates comparable, the WS record while it is
        a candidate, else REST carries; never a comparison of Dates."""
        self._w("ws", _frame("push", vt=0, arrival=1))
        self._w("rest", _frame("rest", "1.1005", "1.1007", vt=9,
                               arrival=10))
        self.assertEqual(self.store.current(self.IID).channel, "ws")
        self.assertEqual(self.store.current(self.IID,
                                            ws_candidate=False).channel,
                         "rest")

    def test_current_once_proven_is_the_newest_and_ws_wins_a_tie(self):
        self._w("ws", _frame("push", vt=0, arrival=1))
        self._w("rest", _frame("rest", "1.1005", "1.1007", vt=9,
                               arrival=10))
        self.assertEqual(self.store.current(
            self.IID, cross_channel_proven=True).channel, "rest")
        self._w("ws", _frame("push", "1.1006", "1.1008", vt=9, arrival=11))
        self.assertEqual(self.store.current(
            self.IID, cross_channel_proven=True).channel, "ws")

    def test_no_record_is_none(self):
        self.assertIsNone(self.store.current(12345))
        self.assertIsNone(self.store.record(12345, "ws"))


class TheMemoryTwinTests(_Rules, SimpleTestCase):

    def setUp(self):
        self.store = _vs().MemoryVenueStore()


class _RedisServer:
    """A private redis-server on a unix socket in a temporary folder."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="vq-redis-")
        self.sock = os.path.join(self.dir, "r.sock")
        self.proc = subprocess.Popen(
            [REDIS_SERVER, "--port", "0", "--unixsocket", self.sock,
             "--save", "", "--appendonly", "no", "--dir", self.dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import redis
        self.client = redis.Redis(unix_socket_path=self.sock)
        deadline = time.monotonic() + 10
        while True:
            try:
                self.client.ping()
                break
            except Exception:  # noqa: BLE001 — still starting
                if time.monotonic() > deadline or self.proc.poll() is not None:
                    self.stop()
                    raise RuntimeError("redis-server did not start")
                time.sleep(0.05)

    def stop(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


@skipUnless(REDIS_SERVER, "no redis-server binary on this host")
class TheRedisScriptTests(_Rules, SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = _RedisServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def setUp(self):
        self.server.client.flushall()
        self.store = _vs().RedisVenueStore(self.server.client)

    def test_the_script_refuses_any_key_outside_vq(self):
        vs = _vs()
        import redis
        script = self.server.client.register_script(vs.CAS_LUA)
        fr = _frame("push")
        with self.assertRaises(redis.ResponseError):
            script(keys=["etoro_rates:r:live:7"], args=fr.args())
        self.assertFalse(self.server.client.exists("etoro_rates:r:live:7"))

    def test_the_records_expire_after_four_days(self):
        self._w("ws", _frame("push"))
        ttl = self.server.client.pttl(_vs().ws_key(self.IID))
        self.assertGreater(ttl, (4 * 86400 - 60) * 1000)
        self.assertLessEqual(ttl, 4 * 86400 * 1000)


@skipUnless(REDIS_SERVER, "no redis-server binary on this host")
class TheTwinsAgreeTests(SimpleTestCase):
    """The same random sequences leave both stores alike, field for
    field (random.Random(seed), 50 seeds)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = _RedisServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def test_fifty_seeds(self):
        import random
        vs = _vs()
        bids = ("1.1000", "1.1001", "0", None, "1.1002", "x", "1.1004")
        for seed in range(50):
            rng = random.Random(seed)
            self.server.client.flushall()
            twin, real = vs.MemoryVenueStore(), vs.RedisVenueStore(
                self.server.client)
            for step in range(40):
                kind = rng.choice(("push", "snapshot", "rest"))
                bid = rng.choice(bids)
                ask = None if bid is None else (
                    str(Decimal(bid) + Decimal("0.0002"))
                    if bid not in ("x",) else "1.1002")
                if rng.random() < 0.1:
                    ask = "0"
                vt = rng.choice((None, 0, 1, 2, 3, 3, 4)) \
                    if kind == "rest" else rng.choice((0, 1, 2, 3, 3, 4))
                fr = _frame(kind, bid, ask, vt=vt, arrival=step,
                            rate_id=rng.choice(("", "", "r1", "r2")))
                channel = "rest" if kind == "rest" else "ws"
                a = twin.write(1, channel, fr)
                b = real.write(1, channel, fr)
                self.assertEqual(a, b, f"seed {seed} step {step}")
            for channel in ("ws", "rest"):
                self.assertEqual(twin.raw(1, channel), real.raw(1, channel),
                                 f"seed {seed} {channel}")
            self.assertEqual(dict(twin.counts), dict(real.counts),
                             f"seed {seed}")


class TheKeysTests(SimpleTestCase):

    def test_the_feeds_keys(self):
        vs = _vs()
        self.assertEqual(vs.ws_key(7), "vq:ws:7")
        self.assertEqual(vs.rest_key(7), "vq:rest:7")
        self.assertEqual(vs.ring_key(7), "vq:ring:7")
        self.assertEqual(vs.record_key("ws", "7"), "vq:ws:7")
        with self.assertRaises(ValueError):
            vs.record_key("engine", 7)

    def test_the_engine_key_is_the_engines_own(self):
        vs = _vs()
        from bot_program.engine import etoro_rates
        for world in ("live", "demo"):
            self.assertEqual(vs.engine_key(world, 7),
                             etoro_rates._key(world, 7))


class TheEngineViewTests(SimpleTestCase):
    """The engine's rates cache is read, never written, before F9."""

    def _cache(self, held):
        c = mock.MagicMock()
        c.get.return_value = held
        return c

    def test_a_dated_answer_reads_as_a_rest_record(self):
        vs = _vs()
        c = self._cache({"lastPrice": "1.1001", "bid": "1.1000",
                         "ask": "1.1002", "at": _at(-3).timestamp(),
                         "date": "2026-11-04T11:59:56Z",
                         "priceRateID": "r9"})
        q = vs.engine_record("live", 7, cache=c)
        self.assertEqual(q.channel, "engine")
        self.assertEqual((q.bid, q.ask), (Decimal("1.1000"),
                                          Decimal("1.1002")))
        self.assertEqual(q.vt, _at(-4))
        self.assertEqual(q.rate_id, "r9")
        self.assertEqual(q.arrival, _at(-3))
        c.get.assert_called_once_with(vs.engine_key("live", 7))
        for name in ("set", "set_many", "add", "delete", "incr", "touch"):
            getattr(c, name).assert_not_called()

    def test_an_answer_without_a_date_or_sides_is_no_record(self):
        vs = _vs()
        for held in (None, {"lastPrice": "1.1", "at": NOW.timestamp()},
                     {"lastPrice": "0", "bid": "0", "ask": "0",
                      "at": NOW.timestamp(), "date": "2026-11-04T12:00:00Z"},
                     {"lastPrice": "1.1", "bid": "1.1", "ask": "1.1002",
                      "at": NOW.timestamp(), "date": "not a date"},
                     "garbage"):
            with self.subTest(held=held):
                self.assertIsNone(vs.engine_record("live", 7,
                                                   cache=self._cache(held)))

    def test_an_unreadable_cache_is_no_record(self):
        vs = _vs()
        c = mock.MagicMock()
        c.get.side_effect = RuntimeError("down")
        self.assertIsNone(vs.engine_record("live", 7, cache=c))
