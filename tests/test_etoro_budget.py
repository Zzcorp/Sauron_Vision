"""THE eTORO REQUEST BUDGET (2026-11-01, bot_program/engine/etoro_budget.py).

One budget per USER KEY, shared by every process (one key opens both
worlds, measured 2026-09-23), in four families (market, account,
execution, lookups), with six priorities:

  * P0 (closes, stop and target moves, close proofs, cancels, the drain,
    the kill switch) and P1 (orders, their last look, their fill lookups,
    the mark of a live row eToro holds no stop for) are NEVER refused:
    counted after their request is sent and off its path (a queue this
    process's flusher thread counts), and a family they take past its
    rate logs its overrun once per window;
  * P2 to P5 take a token BEFORE they are sent, only while the family
    keeps its floor for the priorities above; P3 to P5 also skip while the
    shared 429 pause holds for that key and world;
  * a refused take sends nothing and is never a venue failure: no health
    note (never SICK), no mute of a feed, no failed row, no alarm. The
    mark keeps its last stamp and says its age, the proposal records a
    skip, the candles fall back to the public feed, the sync defers;
  * the cache unreachable: P0 and P1 go through, the rest skip;
  * the key is in no cache key, no log line and no printout.

Run with:  python manage.py test tests.test_etoro_budget
"""
import threading
import time
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import venue_health as vh
from bot_program.engine import etoro_budget as eb
from bot_program.engine import etoro_client as ec
from tests.test_etoro_client import (SEARCH_AAPL, _clear_eligibility,
                                     _client, _FakeSession, _lookup)
from tests.test_etoro_rate_pause import (RATES_429, RATES_OK, _Clock,
                                         _hclient, _hold, _sclient)

#: the user key of the suite's EtoroTrader fixtures (tests.test_etoro_client)
USER_KEY = "user-k"
KH = eb.key_hash(USER_KEY)
ROUTER = "bot_program.engine.broker_router.client_for_symbol"
#: the measured lookup of a position whose open order reads "closed"
CLOSED = _lookup(3)
CLOSED["positionExecutions"][0]["state"] = "closed"


def _fill(kh, family, n, priority=eb.P1):
    """`n` requests already sent at `priority` (counted, never refused),
    and counted in the cache when this returns: a spend only queues its
    count (etoro_budget.spend), so the helper flushes the queue."""
    for _ in range(int(n)):
        eb.spend(kh, family, priority, where="fill")
    eb.flush()


def _wire_calls(fake, sub=""):
    return [c for c in fake.calls if sub in c[1]]


def _wire(env="live"):
    """Every route a site below sends, each answering as measured."""
    return _client([SEARCH_AAPL, RATES_OK,
                    ("GET", "/history/candles", 200, {"candles": []}),
                    ("GET", "/aggregate-portfolio", 200, {}),
                    ("GET", "/portfolio", 200, {"positions": []}),
                    ("POST", "/orders", 200, {"orderId": 77}),
                    ("POST", "market-close-orders", 200,
                     {"orderForClose": {"orderID": 9}}),
                    ("PATCH", "/positions/", 200, {}),
                    ("DELETE", "/orders/", 202, {}),
                    ("GET", "orders:lookup", 200, CLOSED),
                    ("POST", "/eligibility", 200,
                     {"currency": "usd", "eligibilities": []})],
                   env=env)


class _BudgetOn:
    """The budget and the shared pause ON over a clean cache, both on one
    clock, `bclock` (window 10000, its first second)."""

    def setUp(self):
        super().setUp()
        cache.clear()
        eb.reset()
        vh.reset()
        for target, name in ((eb, "BUDGET"), (ec, "RATE_PAUSE")):
            p = mock.patch.object(target, name, True)
            p.start()
            self.addCleanup(p.stop)
        self.bclock = _Clock(t=600_000.0)
        p = mock.patch.object(eb, "_now", self.bclock)
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        self.addCleanup(vh.reset)
        self.addCleanup(eb.reset)
        self.addCleanup(cache.clear)


class _Down:
    """A cache whose every call raises, as Redis down does."""

    def __getattr__(self, name):
        def boom(*args, **kwargs):
            raise ConnectionError("the cache is down")
        return boom


# ── the switch ────────────────────────────────────────────────────────────

class TheSwitchTests(SimpleTestCase):
    """Outside _BudgetOn: the suite's fake wires ask eToro hundreds of
    times in one process minute, so they run with the budget OFF, which is
    exactly today's behaviour; the modules that pin it turn it on."""

    def test_the_suite_runs_with_the_budget_off(self):
        self.assertIs(eb.BUDGET, False)
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_budget.BUDGET = False", src)

    def test_off_counts_nothing_and_refuses_nothing(self):
        cache.clear()
        for p in eb.PRIORITIES:
            eb.take(KH, eb.MARKET, p, world="live", where="ticker")
            eb.spend(KH, eb.MARKET, p, where="ticker")
        self.assertIsNone(cache.get(eb._n_key(KH, eb.MARKET, eb.window())))


# ── the take ──────────────────────────────────────────────────────────────

class TheTakeTests(_BudgetOn, SimpleTestCase):

    def test_the_start_rates_and_floors_are_named_constants(self):
        self.assertEqual((eb.RATE_MARKET_PER_MIN, eb.RATE_ACCOUNT_PER_MIN,
                          eb.RATE_EXECUTION_PER_MIN, eb.RATE_LOOKUPS_PER_MIN),
                         (60, 30, 20, 18))
        self.assertEqual((eb.FLOOR_P2, eb.FLOOR_P3, eb.FLOOR_P4, eb.FLOOR_P5),
                         (0.05, 0.10, 0.40, 0.50))
        self.assertEqual(eb.WINDOW_S, 60)

    def test_the_floors_by_priority_at_the_start_rates(self):
        self.assertEqual({p: eb.limit(eb.MARKET, p) for p in eb.PRIORITIES},
                         {eb.P0: 60, eb.P1: 60, eb.P2: 57, eb.P3: 54,
                          eb.P4: 36, eb.P5: 30})
        # P5 never takes more than half the market family, and a mark
        # leaves six tokens under it for the last looks and the closes
        self.assertEqual(eb.limit(eb.MARKET, eb.P5) * 2, eb.rate(eb.MARKET))
        self.assertEqual(eb.floor_tokens(eb.MARKET, eb.P3), 6)
        self.assertEqual(eb.limit(eb.ACCOUNT, eb.P2), 28)
        # the marks keep 18 tokens a minute the proposals cannot take
        # (2026-11-01, review: 6 at FLOOR_P4 0.20, and an earlier config's
        # proposals left the later configs' marks clock-managed)
        self.assertEqual(eb.limit(eb.MARKET, eb.P3)
                         - eb.limit(eb.MARKET, eb.P4), 18)

    def test_each_priority_is_refused_at_its_own_floor(self):
        def granted(p):
            try:
                eb.take(KH, eb.MARKET, p, world="live", where="ticker")
                return True
            except eb.Refused as e:
                self.assertEqual(e.reason, eb.FLOOR)
                return False
        _fill(KH, eb.MARKET, 29)
        self.assertTrue(granted(eb.P5))              # the 30th
        self.assertFalse(granted(eb.P5))
        _fill(KH, eb.MARKET, 5)                      # 35
        self.assertTrue(granted(eb.P4))              # 36
        self.assertFalse(granted(eb.P4))
        self.assertFalse(granted(eb.P5))
        _fill(KH, eb.MARKET, 17)                     # 53
        self.assertTrue(granted(eb.P3))              # 54
        self.assertFalse(granted(eb.P3))
        self.assertTrue(granted(eb.P2))              # 55
        self.assertTrue(granted(eb.P2))
        self.assertTrue(granted(eb.P2))              # 57
        self.assertFalse(granted(eb.P2))
        n = cache.get(eb._n_key(KH, eb.MARKET, eb.window()))
        self.assertEqual(n, 57, "a refused take gives its token back")

    def test_the_words_lead_with_the_budget_and_carry_no_figure_but_tokens(
            self):
        _fill(KH, eb.MARKET, 30)
        with self.assertRaises(eb.Refused) as cm:
            eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")
        self.assertEqual(str(cm.exception),
                         "eToro budget: market 30/60 this minute, 30 kept "
                         "for higher priorities (P5 candles) — not asked")
        self.assertEqual(cm.exception.why,
                         "eToro budget: market 30/60 this minute, 30 kept "
                         "for higher priorities (P5 candles)")
        self.assertIs(cm.exception.budget_refused, True)
        self.assertNotIsInstance(cm.exception, LookupError,
                                 "never eToro's own 'no such spelling'")

    def test_the_families_are_apart_and_one_key_is_one_budget(self):
        _fill(KH, eb.MARKET, 60)
        eb.take(KH, eb.ACCOUNT, eb.P5, world="live", where="account")
        other = eb.key_hash("another-user-k")
        eb.take(other, eb.MARKET, eb.P5, world="live", where="ticker")
        # the demo and the live world spend the same key's tokens
        with self.assertRaises(eb.Refused):
            eb.take(KH, eb.MARKET, eb.P3, world="demo", where="ticker")

    def test_the_tokens_come_back_as_the_rolling_minute_passes(self):
        # 2026-11-02 (completes E1): a token comes back 60 to 61 s after
        # the request that took it, never at a minute's edge (this was
        # test_a_new_window_has_its_tokens_back: back at +60 s, the next
        # fixed window); the window still names the command's minutes
        _fill(KH, eb.MARKET, 30)
        with self.assertRaises(eb.Refused):
            eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")
        self.assertEqual(eb.window_left_s(), 60.0)
        self.bclock.t += 60
        with self.assertRaises(eb.Refused):
            eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")
        self.bclock.t += 1
        eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")

    def test_a_burst_across_a_minutes_edge_is_judged_on_the_rolling_minute(
            self):
        """2026-11-02 (completes E1, review): fixed windows let a family
        spend its rate on both sides of a minute's edge, twice its rate
        inside one rolling minute. A take is judged on every request of
        its family sent in the last 60 s."""
        self.bclock.t += 59                     # the window's last second
        _fill(KH, eb.MARKET, 30)
        before = eb.window()
        self.bclock.t += 2                      # the next window
        self.assertEqual(eb.window(), before + 1)
        with self.assertRaises(eb.Refused) as cm:
            eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")
        self.assertEqual(cm.exception.reason, eb.FLOOR)
        self.assertEqual(cm.exception.why,
                         "eToro budget: market 30/60 this minute, 30 kept "
                         "for higher priorities (P5 candles)")
        self.bclock.t += 59                     # 61 s after the burst
        eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")

    def test_no_rolling_minute_holds_more_than_a_priority_may_take(self):
        # a take every half second for three minutes, starting 15 s before
        # a minute's edge: fixed windows granted 30 just before the edge
        # and 30 just after it, 60 inside one rolling minute
        self.bclock.t += 45
        granted = []
        for _ in range(360):
            try:
                eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")
                granted.append(self.bclock.t)
            except eb.Refused as e:
                self.assertEqual(e.reason, eb.FLOOR)
            self.bclock.t += 0.5
        cap = eb.limit(eb.MARKET, eb.P5)
        worst = max(sum(1 for g in granted if t - 60 < g <= t)
                    for t in granted)
        self.assertLessEqual(worst, cap)
        self.assertGreaterEqual(len(granted), 2 * cap,
                                "the rate is still spent, minute after "
                                "minute")

    def test_p0_and_p1_past_the_rolling_minute_are_an_overrun(self):
        self.bclock.t += 50
        _fill(KH, eb.MARKET, 60)                # inside the rate
        self.bclock.t += 20                     # the next window
        with self.assertLogs("bot_program.engine.etoro_budget",
                             level="WARNING") as logs:
            eb.spend(KH, eb.MARKET, eb.P0, where="close")
            eb.flush()
        over = [m for m in logs.output
                if "over its 60 a minute (61 this minute)" in m]
        self.assertEqual(len(over), 1, logs.output)
        self.assertEqual(cache.get(eb._o_key(KH, eb.MARKET, eb.window())), 1)

    def test_the_take_is_atomic_under_threads(self):
        granted, refused = [], []
        start = threading.Barrier(16)

        def worker():
            start.wait()
            for _ in range(10):
                try:
                    eb.take(KH, eb.MARKET, eb.P5, world="live",
                            where="candles")
                    granted.append(1)
                except eb.Refused as e:
                    refused.append(e.reason)
        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(granted), eb.limit(eb.MARKET, eb.P5))
        self.assertEqual(len(granted) + len(refused), 160)
        self.assertEqual(set(refused), {eb.FLOOR})
        self.assertEqual(cache.get(eb._n_key(KH, eb.MARKET, eb.window())),
                         30)
        self.assertEqual(cache.get(eb._p_key(KH, eb.MARKET, eb.window(),
                                             eb.P5)), 30)

    def test_p0_and_p1_are_never_refused_and_their_overrun_is_logged_once(
            self):
        _fill(KH, eb.MARKET, 60)
        with self.assertLogs("bot_program.engine.etoro_budget",
                             level="WARNING") as logs:
            for p in (eb.P0, eb.P1, eb.P0):
                eb.take(KH, eb.MARKET, p, world="live", where="ticker")
                eb.spend(KH, eb.MARKET, p, where="ticker")
            eb.flush()           # the queued counts, counted (and logged)
        over = [m for m in logs.output if "over its 60 a minute" in m]
        self.assertEqual(len(over), 1, logs.output)
        self.assertIn("sent anyway: P0 and P1 are never refused", over[0])
        win = eb.window()
        self.assertEqual(cache.get(eb._n_key(KH, eb.MARKET, win)), 63)
        self.assertEqual(cache.get(eb._o_key(KH, eb.MARKET, win)), 3)
        # the next window's overrun is logged again (2026-11-02: 61 s on,
        # once the rolling minute no longer holds the 63 above)
        self.bclock.t += 61
        _fill(KH, eb.MARKET, 60)
        with self.assertLogs("bot_program.engine.etoro_budget",
                             level="WARNING") as logs:
            eb.spend(KH, eb.MARKET, eb.P0, where="close")
            eb.flush()
        self.assertEqual(len([m for m in logs.output
                              if "over its 60 a minute" in m]), 1)

    def test_the_cache_unreachable_lets_p0_and_p1_through_and_skips_the_rest(
            self):
        with mock.patch.object(eb, "_cache", return_value=_Down()), \
                self.assertLogs("bot_program.engine.etoro_budget",
                                level="WARNING") as logs:
            for _ in range(3):
                eb.spend(KH, eb.EXECUTION, eb.P0, where="close")
                eb.spend(KH, eb.MARKET, eb.P1, where="ticker")
            for p in (eb.P2, eb.P3, eb.P4, eb.P5):
                with self.assertRaises(eb.Refused) as cm:
                    eb.take(KH, eb.MARKET, p, world="live", where="ticker")
                self.assertEqual(cm.exception.reason, eb.CACHE)
                self.assertTrue(str(cm.exception).startswith(
                    "eToro budget: its cache is unreachable "
                    "(ConnectionError; "), str(cm.exception))
        self.assertEqual(eb.UNBUDGETED, {eb.P0: 3, eb.P1: 3},
                         "every request sent unbudgeted is recorded")
        said = [m for m in logs.output if "cache is unreachable" in m]
        self.assertEqual(len(said), 2, "once for what went, once for what "
                                       "was not asked, per window")
        self.assertIn("sent unbudgeted", said[0])
        self.assertIn("not asked", said[1])


# ── the client: every site at its priority ────────────────────────────────

class TheSitesTests(_BudgetOn, SimpleTestCase):

    def _spy(self, order=None):
        seen = []
        real_take, real_spend = eb.take, eb.spend

        def take(kh, family, priority, **kw):
            seen.append(("take", family, priority, kw.get("where")))
            if order is not None:
                order.append("take")
            return real_take(kh, family, priority, **kw)

        def spend(kh, family, priority, **kw):
            seen.append(("spend", family, priority, kw.get("where")))
            if order is not None:
                order.append("spend")
            return real_spend(kh, family, priority, **kw)
        for name, fn in (("take", take), ("spend", spend)):
            p = mock.patch.object(eb, name, fn)
            p.start()
            self.addCleanup(p.stop)
        return seen

    def _wire(self, env="live"):
        return _wire(env)

    def test_the_reads_take_the_callers_priority_and_p1_outside_any(self):
        seen = self._spy()
        t, _ = self._wire()
        t.ticker("AAPL")
        self.assertEqual(seen, [("spend", "market", eb.P1, "search"),
                                ("spend", "market", eb.P1, "ticker")])
        seen.clear()
        with eb.at(eb.P3, "mark"):
            self._wire()[0].ticker("AAPL")
        self.assertEqual(seen, [("take", "market", eb.P3, "search"),
                                ("take", "market", eb.P3, "ticker")])
        seen.clear()
        with eb.at(eb.P4, "proposal"):
            t.ticker("AAPL")
        self.assertEqual(seen, [("take", "market", eb.P4, "ticker")])
        seen.clear()
        with eb.at(eb.P2, "account sync"):
            t.account()
            t.get_positions()
        self.assertEqual(seen, [("take", "account", eb.P2, "account"),
                                ("take", "account", eb.P2, "portfolio")])
        seen.clear()
        t.eligibility("AAPL")
        t.ping()
        self.assertEqual(seen, [("spend", "account", eb.P1, "eligibility"),
                                ("spend", "account", eb.P1, "account")])

    def test_the_candles_are_p5_unless_a_caller_set_more(self):
        seen = self._spy()
        t, _ = self._wire()
        t.klines("AAPL", interval="4h", limit=5)
        self.assertEqual(seen, [("take", "market", eb.P5, "search"),
                                ("take", "market", eb.P5, "candles")])
        seen.clear()
        with eb.at(eb.P2, "a caller that set more"):
            t.klines("AAPL", interval="4h", limit=5)
        self.assertEqual(seen, [("take", "market", eb.P2, "candles")])

    def test_the_order_and_its_lookups_are_p1_whatever_the_scope(self):
        seen = self._spy()
        for scope in (None, eb.P3, eb.P5):
            seen.clear()
            t, _ = self._wire()
            with mock.patch("time.sleep"):
                if scope is None:
                    t.market_order("AAPL", "BUY", 1.0, stop_loss=90.0,
                                   take_profit=110.0)
                else:
                    with eb.at(scope):
                        t.market_order("AAPL", "BUY", 1.0, stop_loss=90.0,
                                       take_profit=110.0)
            self.assertTrue(seen)
            self.assertEqual({s[2] for s in seen}, {eb.P1}, (scope, seen))
            self.assertEqual({s[0] for s in seen}, {"spend"})
            self.assertIn(("spend", "execution", eb.P1, "order"), seen)
            self.assertIn(("spend", "lookups", eb.P1, "lookup"), seen)
        seen.clear()
        t.order_status("77")
        self.assertEqual(seen, [("spend", "lookups", eb.P1, "lookup")])

    def test_closes_moves_proofs_and_cancels_are_p0_whatever_the_scope(self):
        seen = self._spy()
        for scope in (None, eb.P1, eb.P3, eb.P5):
            seen.clear()
            t, _ = self._wire()
            with mock.patch("time.sleep"), eb.at(
                    eb.P5 if scope is None else scope):
                res = t.close_position("555", "AAPL", 1.0,
                                       open_order_id="77")
                t.modify_protective("555", 95.0)
                t.modify_target("555", 120.0)
                t.position_state("77", attempts=1, delay=0.0)
                t.cancel_order("78")
            self.assertEqual(res["status"], "FILLED")
            self.assertEqual({s[2] for s in seen}, {eb.P0}, (scope, seen))
            self.assertEqual({s[0] for s in seen}, {"spend"})
            for site in (("execution", "close"), ("execution", "patch"),
                         ("lookups", "lookup"), ("market", "search")):
                self.assertIn(("spend",) + site[:1] + (eb.P0,) + site[1:],
                              seen)

    def test_the_cancel_its_delete_and_its_proof_are_p0(self):
        seen = self._spy()
        t, fake = _sclient({("GET", "orders:lookup"): [
            (200, {"status": {"id": 11, "name": "WaitingForMarket"}}),
            (200, {"status": {"id": 7, "name": "Canceled"}})]},
            routes=[("DELETE", "/orders/", 202, {})])
        with mock.patch("time.sleep"), eb.at(eb.P5):
            self.assertIs(t.cancel_order("78"), True)
        self.assertEqual(len(_wire_calls(fake, "/orders/78")), 1)
        self.assertIn(("spend", "execution", eb.P0, "cancel"), seen)
        self.assertEqual({s[2] for s in seen}, {eb.P0}, seen)
        self.assertEqual({s[0] for s in seen}, {"spend"})

    def test_a_write_is_counted_after_it_is_sent_never_before(self):
        order = []
        self._spy(order=order)
        t, fake = self._wire()
        t.instrument_id("AAPL")
        real = fake._hit

        def hit(method, url, **kw):
            order.append(f"{method} {url.split('/')[-1]}")
            return real(method, url, **kw)
        fake._hit = hit
        order.clear()
        t.close_position("555", "AAPL", 1.0)
        t.modify_protective("555", 95.0)
        self.assertEqual(order, ["POST 555", "spend", "PATCH 555", "spend"])

    def test_a_refused_read_sends_nothing_and_is_no_venue_failure(self):
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3))
        t, fake = _client([SEARCH_AAPL, RATES_OK], env="live")
        with eb.at(eb.P3, "mark"), self.assertRaises(eb.Refused) as cm:
            t.ticker("AAPL")
        self.assertEqual(fake.calls, [])
        self.assertEqual(t.wire_reads, 0)
        self.assertEqual(vh._load(vh._key("etoro", "live")), {})
        self.assertIsNone(vh.sick("etoro", "live"))
        self.assertEqual(str(cm.exception),
                         "eToro budget: market 54/60 this minute, 6 kept for "
                         "higher priorities (P3 mark) — not asked")
        # the floor is the lower priorities' alone: the same read at P1 goes
        self.assertEqual(float(t.ticker("AAPL")["lastPrice"]), 100.0)

    def test_a_retry_is_counted_and_never_refused(self):
        # XAGUSD is pinned (VENUE_ID_PINS): no /search, one token per ask
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3) - 1)
        t, fake = _sclient({("GET", "/rates"): [
            (503, {}), (200, {"rates": [{"bid": 30.0, "ask": 30.2,
                                         "lastExecution": 30.1}]})]})
        with eb.at(eb.P3, "mark"), mock.patch("time.sleep"):
            self.assertEqual(float(t.ticker("XAGUSD")["lastPrice"]), 30.1)
        self.assertEqual(len(_wire_calls(fake, "/rates")), 2)
        eb.flush()                     # the retry's count, queued once sent
        self.assertEqual(cache.get(eb._n_key(KH, eb.MARKET, eb.window())),
                         55, "the retry went past P3's limit, counted")

    def test_the_cache_down_sends_the_close_and_skips_the_mark(self):
        t, fake = self._wire()
        with mock.patch.object(eb, "_cache", return_value=_Down()), \
                mock.patch("time.sleep"):
            res = t.close_position("555", "AAPL", 1.0, open_order_id="77")
            with eb.at(eb.P3, "mark"), self.assertRaises(eb.Refused):
                t.ticker("AAPL")
        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(len(_wire_calls(fake, "market-close-orders")), 1)
        self.assertEqual(_wire_calls(fake, "/rates"), [])
        self.assertGreaterEqual(eb.UNBUDGETED.get(eb.P0, 0), 3)


# ── the spend queue: P0 and P1 counted off the request path ───────────────

class _Recorder:
    """The budget's cache: every call the CALLING thread makes is written
    in `events` (the flusher's calls are its own thread's, off the path).
    With a `gate`, each call of any thread first waits for it, at most
    `stall_s`: a cache that stalls (a fork for BGSAVE, an fsync, a frozen
    container)."""

    def __init__(self, events, *, gate=None, stall_s=0.0):
        self._events = events
        self._me = threading.get_ident()
        self._gate = gate
        self._stall_s = stall_s

    def __getattr__(self, name):
        fn = getattr(cache, name)

        def call(*args, **kwargs):
            if threading.get_ident() == self._me:
                self._events.append(f"cache {name}")
            if self._gate is not None:
                self._gate.wait(self._stall_s)
            return fn(*args, **kwargs)
        return call


class TheSpendQueueTests(_BudgetOn, SimpleTestCase):
    """A P0 or P1 request is counted OFF its path (2026-11-01, review): the
    spend only queues the count and wakes this process's flusher thread,
    which does the cache work. Six cache round trips per request (eight on
    a process's first of a window) used to stand between a close POST and
    its proof, between the proofs, and between two closes of the kill
    switch. Every take drains the queue first, so a take is still judged
    on every request this process sent."""

    def _two_closes(self, t, fake, events):
        """Two closes of the kill switch, each its POST and its proof;
        every request to the wire written in `events` beside the cache
        calls of this thread."""
        real = fake._hit

        def hit(method, url, **kw):
            events.append(f"wire {method} " + (
                "lookup" if "orders:lookup" in url else
                "close" if "market-close-orders" in url else url))
            return real(method, url, **kw)
        fake._hit = hit
        with mock.patch("time.sleep"), eb.at(eb.P0, "kill switch"):
            for pid, oid in (("555", "77"), ("556", "78")):
                res = t.close_position(pid, "AAPL", 1.0, open_order_id=oid)
                self.assertEqual(res["status"], "FILLED")

    def _counted(self):
        win = eb.window()
        return (cache.get(eb._n_key(KH, eb.EXECUTION, win)),
                cache.get(eb._n_key(KH, eb.LOOKUPS, win)),
                cache.get(eb._p_key(KH, eb.EXECUTION, win, eb.P0)))

    def test_no_cache_call_stands_between_a_close_its_proof_and_the_next(
            self):
        t, fake = _wire()
        t.instrument_id("AAPL")                  # the id warm: no /search
        eb.flush()
        events = []
        with mock.patch.object(eb, "_cache", return_value=_Recorder(events)):
            self._two_closes(t, fake, events)
            on_the_path = [e for e in events if e.startswith("cache")]
        self.assertEqual([e for e in events if e.startswith("wire")],
                         ["wire POST close", "wire GET lookup",
                          "wire POST close", "wire GET lookup"])
        self.assertEqual(on_the_path, [], events)
        eb.flush()
        self.assertEqual(self._counted(), (2, 2, 2),
                         "every close and proof counted, once sent")

    def test_a_stalled_cache_holds_neither_a_close_nor_its_proof(self):
        t, fake = _wire()
        t.instrument_id("AAPL")
        eb.flush()
        gate, events = threading.Event(), []
        stalled = _Recorder(events, gate=gate, stall_s=1.0)
        with mock.patch.object(eb, "_cache", return_value=stalled):
            started = time.monotonic()
            self._two_closes(t, fake, events)
            took = time.monotonic() - started
            gate.set()                           # the cache answers again
            eb.flush()
        self.assertLess(took, 0.75, f"the closes waited {took:.2f}s on the "
                                    f"budget's cache")
        self.assertEqual(self._counted(), (2, 2, 2))

    def test_the_flusher_counts_what_was_sent_with_no_take_and_no_flush(
            self):
        key = eb._n_key(KH, eb.EXECUTION, eb.window())
        eb.spend(KH, eb.EXECUTION, eb.P0, where="close")
        deadline = time.monotonic() + 5.0
        while cache.get(key) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(cache.get(key), 1)

    def test_a_take_drains_the_queue_before_it_is_judged(self):
        for _ in range(eb.limit(eb.MARKET, eb.P3)):
            eb.spend(KH, eb.MARKET, eb.P1, where="ticker")      # queued
        with self.assertRaises(eb.Refused) as cm:
            eb.take(KH, eb.MARKET, eb.P3, world="live", where="ticker")
        self.assertEqual(cm.exception.reason, eb.FLOOR)
        self.assertEqual(cm.exception.why,
                         "eToro budget: market 54/60 this minute, 6 kept for "
                         "higher priorities (P3 mark)")

    def test_a_forked_child_counts_its_own_and_never_waits_on_its_parent(
            self):
        parents, theirs = eb._DRAIN, eb._SPENT
        parents.acquire()             # a drain the parent was in at the fork
        try:
            # a count the parent queued and had not counted yet
            theirs.append((KH, eb.MARKET, eb.P1, "ticker", "", eb._now()))
            eb._after_fork_in_child()
            self.assertIsNot(eb._SPENT, theirs)
            self.assertEqual(len(eb._SPENT), 0,
                             "the parent's counts are the parent's")
            self.assertIsNot(eb._DRAIN, parents)
            eb.spend(KH, eb.EXECUTION, eb.P0, where="close")
            eb.flush()                # never waits on the parent's lock
        finally:
            theirs.clear()            # the parent's, never this test's
            parents.release()
        win = eb.window()
        self.assertEqual(cache.get(eb._n_key(KH, eb.EXECUTION, win)), 1)
        self.assertIsNone(cache.get(eb._n_key(KH, eb.MARKET, win)))


# ── the account helpers: a refusal is raised, never a failed read ─────────

class TheAccountHelpersTests(_BudgetOn, TestCase):
    """net_liquidation, margin_cells, balance_usdt and broker_portfolio
    RAISE a read the budget did not send (2026-11-01, review), as
    account_snapshot does. Answered as a failed read (None, 0.0), the sync
    counted it as a missed pass toward its "unreachable" alert, and the
    smoke said "the adapter swallowed the failure"."""

    KU = eb.key_hash("u")

    def _trader(self, total=1000.0):
        t = ec.EtoroTrader("k", "u", env="live")
        t._session = _FakeSession([
            ("GET", "/aggregate-portfolio", 200, {
                "accountCurrency": "USD", "accountTotals": {
                    "accountTotalValue": total,
                    "accountAvailableCash": 400.0,
                    "accountTotalUsedMargin": 0.0}}),
            ("GET", "/portfolio", 200, {"positions": []})])
        return t

    def test_each_raises_the_refusal_and_sends_nothing(self):
        t = self._trader()
        _fill(self.KU, eb.ACCOUNT, eb.limit(eb.ACCOUNT, eb.P2))
        for name in ("net_liquidation", "margin_cells", "balance_usdt",
                     "broker_portfolio"):
            with self.subTest(name), eb.at(eb.P2, "account sync"), \
                    self.assertRaises(eb.Refused):
                getattr(t, name)()
        self.assertEqual(t._session.calls, [])

    def test_outside_a_scope_they_are_p1_and_answer_as_before(self):
        t = self._trader()
        _fill(self.KU, eb.ACCOUNT, eb.rate(eb.ACCOUNT))
        self.assertEqual(t.net_liquidation(), (1000.0, "USD"))
        self.assertEqual(t.balance_usdt(), 400.0)
        self.assertEqual(t.margin_cells()["available_cash"], 400.0)
        self.assertEqual(t.broker_portfolio(), [])

    def test_a_failed_read_still_answers_as_a_failed_read(self):
        t = ec.EtoroTrader("k", "u", env="live")
        t._session = _FakeSession([("GET", "/aggregate-portfolio", 500, {}),
                                   ("GET", "/portfolio", 500, {})])
        with mock.patch("time.sleep"), eb.at(eb.P2, "account sync"):
            self.assertIsNone(t.net_liquidation())
            self.assertIsNone(t.margin_cells())
            self.assertEqual(t.balance_usdt(), 0.0)
            self.assertIsNone(t.broker_portfolio())

    def test_a_sync_whose_portfolio_read_is_refused_defers_with_no_miss(
            self):
        from bot_program.tasks import sync_etoro_accounts
        from tests.test_sync_walks_etoro import _etoro
        user = User.objects.create_user("budget_helpers", password="x")
        acct = _etoro(user, demo=False, is_primary_for_stocks=True)
        # a total of 0 reads as no equity; the aggregate takes the
        # family's last P2 token and the portfolio finds none
        t = self._trader(total=0.0)
        _fill(self.KU, eb.ACCOUNT, eb.limit(eb.ACCOUNT, eb.P2) - 1)
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                        return_value=t), \
                mock.patch("bot_program.notifications."
                           "notify_broker_unreachable") as told, \
                self.assertLogs("bot_program", level="INFO") as logs:
            out = sync_etoro_accounts.__wrapped__.__wrapped__()
        self.assertEqual(len(_wire_calls(t._session, "/aggregate-portfolio")),
                         1)
        self.assertEqual(_wire_calls(t._session, "/portfolio"), [])
        self.assertEqual((out["attempted"], out["unreachable"],
                          out.get("deferred", 0)), (0, 0, 1), out)
        self.assertIsNone(cache.get(f"broker_sync:miss:etoro:{acct.pk}"))
        told.assert_not_called()
        self.assertFalse([ln for ln in logs.output
                          if "failed" in ln or "consecutive miss" in ln],
                         logs.output)


# ── the shared 429 pause ──────────────────────────────────────────────────

class TheSharedPauseTests(_BudgetOn, SimpleTestCase):

    def _meet_429(self, seconds="40"):
        a, _ = _hclient([SEARCH_AAPL[:4],
                         RATES_429 + ({"Retry-After": seconds},)])
        with self.assertRaises(Exception):
            a.ticker("AAPL")
        return a

    def test_the_pause_lives_in_the_cache_and_no_process_keeps_a_copy(self):
        self.assertFalse(hasattr(ec, "_RATE_PAUSE"),
                         "the per-process dict is gone")
        self._meet_429()
        held = cache.get(eb._pause_key(KH, "live"))
        self.assertEqual(held, {"end": self.bclock.t + 40, "at": self.bclock.t})

    def test_a_429_one_client_met_holds_another_client_of_the_same_key(self):
        self._meet_429()
        # another client of the same key: what another process builds
        b, fake = _hclient([SEARCH_AAPL[:4], RATES_OK[:4],
                            ("GET", "/aggregate-portfolio", 200, {})])
        self.assertEqual(b.rate_pause_s(), 40.0)
        self.assertEqual(vh.pause_s(b), 40.0, "today's readers read it")
        for p in (eb.P3, eb.P4, eb.P5):
            with self.subTest(priority=p), eb.at(p), \
                    self.assertRaises(eb.Refused) as cm:
                b.ticker("AAPL")
            self.assertEqual(cm.exception.reason, eb.PAUSE)
            self.assertIn("the 429 pause holds (live, 40s left", str(
                cm.exception))
        self.assertEqual(fake.calls, [])
        # P2 reads no pause, nor does a read no caller classified (P1)
        with eb.at(eb.P2):
            b.account()
        self.assertEqual(float(b.ticker("AAPL")["lastPrice"]), 100.0)
        # another key, another world: nothing holds
        other = ec.EtoroTrader("api-k", "another-user-k", env="live")
        self.assertEqual(other.rate_pause_s(), 0.0)
        self.assertEqual(_hclient([], env="demo")[0].rate_pause_s(), 0.0)
        self.bclock.t += 40
        self.assertEqual(b.rate_pause_s(), 0.0)
        with eb.at(eb.P3):
            b.ticker("AAPL")

    def test_two_429s_at_once_grant_one_pause(self):
        self._meet_429("40")
        self.bclock.t += 5
        a2 = self._meet_429("90")
        self.assertEqual(a2.rate_pause_s(), 35.0, "the first pause stands")

    def test_a_p0_read_that_meets_a_429_grants_the_pause_off_its_path(self):
        """2026-11-02 (completes E1, review): a P0 read that met eToro's
        429 — the kill switch's or the drain's mark, the /search a close's
        cold id costs — granted the shared pause on its own thread: a read
        and a write of the budget's cache between that answer and the next
        close, held by a cache that stalls. The grant is queued for this
        process's flusher now, dated at the 429, and every take drains it
        first."""
        a, fake = _hclient([SEARCH_AAPL[:4],
                            RATES_429 + ({"Retry-After": "40"},)])
        a.instrument_id("AAPL")                  # the id warm: no /search
        eb.flush()
        at = self.bclock.t
        gate, events = threading.Event(), []
        stalled = _Recorder(events, gate=gate, stall_s=1.0)
        with mock.patch.object(eb, "_cache", return_value=stalled):
            started = time.monotonic()
            with eb.at(eb.P0, "kill switch"), \
                    self.assertRaises(requests.HTTPError):
                a.ticker("AAPL")
            took = time.monotonic() - started
            on_the_path = [e for e in events if e.startswith("cache")]
            gate.set()                           # the cache answers again
            eb.flush()
        self.assertEqual(on_the_path, [], events)
        self.assertLess(took, 0.75, f"the P0 read waited {took:.2f}s on the "
                                    f"budget's cache")
        self.assertEqual(len(_wire_calls(fake, "/rates")), 1)
        self.assertEqual(cache.get(eb._pause_key(KH, "live")),
                         {"end": at + 40, "at": at},
                         "granted all the same, dated at the 429")
        # the next take of this process is judged on it
        b, _ = _hclient([SEARCH_AAPL[:4], RATES_OK[:4]])
        with eb.at(eb.P3), self.assertRaises(eb.Refused) as cm:
            b.ticker("AAPL")
        self.assertEqual(cm.exception.reason, eb.PAUSE)

    def _no_flusher(self):
        """The budget's drains on THIS thread only: a flusher thread that
        runs (an earlier spend started it) drains nothing meanwhile."""
        me, real = threading.get_ident(), eb._drain

        def drain(wait=None):
            if threading.get_ident() == me:
                return real(wait)
        return mock.patch.object(eb, "_drain", drain)

    def test_a_take_drains_a_queued_grant_before_it_is_judged(self):
        a, _ = _hclient([SEARCH_AAPL[:4],
                         RATES_429 + ({"Retry-After": "40"},)])
        a.instrument_id("AAPL")
        eb.flush()
        with self._no_flusher():
            with eb.at(eb.P0, "pending-close drain"), \
                    self.assertRaises(requests.HTTPError):
                a.ticker("AAPL")
            self.assertIsNone(cache.get(eb._pause_key(KH, "live")),
                              "queued, not yet written")
            with self.assertRaises(eb.Refused) as cm:
                eb.take(KH, eb.MARKET, eb.P4, world="live", where="ticker")
        self.assertEqual(cm.exception.reason, eb.PAUSE)

    def test_below_p0_the_429_still_grants_the_pause_on_its_path(self):
        # a mark (P3) or a read no caller classified (P1): the pause holds
        # the moment the read returns, as since 2026-11-01
        for scope in (None, eb.P3):
            eb.forget_pauses()
            a, _ = _hclient([SEARCH_AAPL[:4],
                             RATES_429 + ({"Retry-After": "40"},)])
            with self.subTest(scope=scope), self._no_flusher():
                if scope is None:
                    with self.assertRaises(requests.HTTPError):
                        a.ticker("AAPL")
                else:
                    with eb.at(scope), self.assertRaises(requests.HTTPError):
                        a.ticker("AAPL")
                self.assertEqual(
                    cache.get(eb._pause_key(KH, "live")),
                    {"end": self.bclock.t + 40, "at": self.bclock.t})

    def test_p0_never_reads_it(self):
        self._meet_429()
        for scope in (None, eb.P5):
            t, fake = _wire()
            with mock.patch("time.sleep"), eb.at(
                    eb.P5 if scope else eb.P0):
                res = t.close_position("555", "AAPL", 1.0,
                                       open_order_id="77")
                self.assertTrue(t.modify_protective("555", 95.0)["ok"])
                self.assertEqual(t.position_state("77", attempts=1,
                                                  delay=0.0), "closed")
                t.cancel_order("78")
            self.assertEqual(res["status"], "FILLED")
            for sub in ("market-close-orders", "/positions/555",
                        "orders:lookup"):
                self.assertTrue(_wire_calls(fake, sub), sub)


# ── the engine: the mark and the proposal ─────────────────────────────────

class TheMarkTests(_BudgetOn, TestCase):
    """The mark of a row whose stop and target REST AT eTORO (protected):
    P3, skipped when the market family keeps its floor. A live row eToro
    holds no stop for is marked at P1 (TheBareRowMarkTests)."""

    def setUp(self):
        super().setUp()
        from tests.test_exit_truth import _cfg, _trade, _user
        self.cfg = _cfg(_user("budget_mark"), name="BM")
        self.stamped = (timezone.now() - timedelta(minutes=12)).isoformat()
        self.trade = _trade(self.cfg, metadata={
            "initial_stop_loss": 98.0, "protected": True,
            "venue_mark": {"price": 101.0, "at": self.stamped,
                           "source": "etoro", "via": "tick"}})

    def _tick(self, t):
        from bot_program.asset_engine.stock_bot import StockBot
        with mock.patch(ROUTER, return_value=t):
            return StockBot(self.cfg).manage_positions()

    def test_a_refused_mark_keeps_its_stamp_says_its_age_and_is_no_failure(
            self):
        from bot_program.asset_engine import skips
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3))
        t, fake = _client([SEARCH_AAPL, RATES_OK], env="live")
        with mock.patch("bot_program.notifications.notify_staff") as told:
            self._tick(t)
        self.assertEqual(_wire_calls(fake, "/rates"), [])
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "OPEN")
        self.assertEqual(self.trade.metadata["venue_mark"]["at"],
                         self.stamped, "the last stamp is kept")
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertEqual(note["detail"],
                         "open position only clock-managed: the mark was not "
                         "asked (eToro budget: market 54/60 this minute, 6 "
                         "kept for higher priorities (P3 mark)); last venue "
                         "stamp 12 min old")
        self.assertEqual(vh._load(vh._key("etoro", "live")), {})
        told.assert_not_called()

    def test_the_mark_is_taken_at_p3(self):
        seen = []
        real = eb.take

        def take(kh, family, priority, **kw):
            seen.append((family, priority, kw.get("where"), kw.get("why")))
            return real(kh, family, priority, **kw)
        t, fake = _client([SEARCH_AAPL, RATES_OK], env="live")
        with mock.patch.object(eb, "take", take):
            self._tick(t)
        self.assertIn(("market", eb.P3, "ticker", "mark"), seen)
        self.assertEqual(len(_wire_calls(fake, "/rates")), 1)


class TheBareRowMarkTests(_BudgetOn, TestCase):
    """A LIVE eToro row whose venue holds NO stop (a held order that filled
    with no stop read on the position: _finish_working_entry's
    venue_stop_unread, "bot-side management") has its bot-side stop as its
    only stop. Its mark is P1 (2026-11-01, review): counted, never refused,
    never paused, so that stop runs every tick as it did before the
    budget. At P3 a refused mark left the position with no stop at all for
    the tick."""

    #: eToro's rate under the row's 98 stop (long 10 AAPL at 100)
    RATES_UNDER_STOP = ("GET", "/rates", 200, {"rates": [
        {"bid": 97.4, "ask": 97.6, "lastExecution": 97.5}]})

    def setUp(self):
        super().setUp()
        from tests.test_exit_truth import _cfg, _trade, _user
        self.cfg = _cfg(_user("budget_bare"), name="BB")
        self.trade = _trade(self.cfg, metadata={
            "initial_stop_loss": 98.0, "protected": False,
            "venue_stop_unread": True, "broker": "etoro",
            "broker_env": "live", "broker_position_id": "555"})
        self.closes = []

    def _tick(self):
        from bot_program.asset_engine.stock_bot import StockBot
        t, fake = _client([SEARCH_AAPL, self.RATES_UNDER_STOP], env="live")
        bot = StockBot(self.cfg)

        def close(trade, price, client, reason=""):
            self.closes.append((trade.id, str(price), reason))
            return True
        bot._close_trade = close
        with mock.patch(ROUTER, return_value=t), \
                mock.patch("bot_program.notifications.notify_staff"):
            bot.manage_positions()
        return fake

    def _assert_marked_and_stopped(self, fake):
        self.assertEqual(len(_wire_calls(fake, "/rates")), 1,
                         "the mark was read")
        self.assertEqual(self.closes, [(self.trade.id, "97.5", "SL")],
                         "and its only stop ran")
        self.assertEqual(vh._load(vh._key("etoro", "live")), {})

    def test_at_the_p3_limit_its_mark_is_read_and_its_stop_runs(self):
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3))
        self._assert_marked_and_stopped(self._tick())

    def test_the_shared_pause_never_holds_its_mark(self):
        _hold("live", 40, self.bclock)
        self._assert_marked_and_stopped(self._tick())

    def test_the_cache_unreachable_never_holds_its_mark(self):
        with mock.patch.object(eb, "_cache", return_value=_Down()):
            fake = self._tick()
        self._assert_marked_and_stopped(fake)

    def test_its_mark_is_counted_at_p1_and_a_protected_rows_taken_at_p3(
            self):
        seen = []
        real_take, real_spend = eb.take, eb.spend

        def take(kh, family, priority, **kw):
            seen.append(("take", family, priority, kw.get("where"),
                         kw.get("why")))
            return real_take(kh, family, priority, **kw)

        def spend(kh, family, priority, **kw):
            seen.append(("spend", family, priority, kw.get("where"),
                         kw.get("why")))
            return real_spend(kh, family, priority, **kw)
        with mock.patch.object(eb, "take", take), \
                mock.patch.object(eb, "spend", spend):
            self._tick()
        self.assertIn(("spend", "market", eb.P1, "ticker",
                       "mark, no stop at the venue"), seen)
        self.assertFalse([s for s in seen if s[0] == "take"], seen)
        # the same row once eToro holds its stop: P3 again
        self.trade.metadata = {"initial_stop_loss": 98.0, "protected": True,
                               "broker": "etoro", "broker_env": "live",
                               "broker_position_id": "555"}
        self.trade.save(update_fields=["metadata"])
        seen.clear()
        with mock.patch.object(eb, "take", take), \
                mock.patch.object(eb, "spend", spend):
            self._tick()
        self.assertIn(("take", "market", eb.P3, "ticker", "mark"), seen)

    def test_a_row_the_engine_booked_from_a_held_order_with_no_stop(self):
        """No hand-written metadata: a WORKING row whose held order fills
        and whose venue reports no stop, through _finish_working_entry;
        then a tick at P3's limit."""
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.venue_exit import venue_levels
        from tests.test_exit_truth import _trade
        self.trade.delete()
        row = _trade(self.cfg, broker_order_id="77", metadata={
            "initial_stop_loss": 98.0, "entry_working": True,
            "qty_requested": 10.0, "protected": False,
            "protected_on_fill_expected": False})
        t, _ = _client([SEARCH_AAPL, self.RATES_UNDER_STOP], env="live")
        with mock.patch("bot_program.notifications.notify_staff"):
            StockBot(self.cfg)._finish_working_entry(
                row, t, qty=10.0, price=100.0, source="broker",
                venue={"state": "filled", "filled": 10.0, "avgPrice": 100.0,
                       "positionId": "555"})
        row.refresh_from_db()
        self.assertTrue(row.metadata.get("venue_stop_unread"))
        self.assertEqual(venue_levels(row), {}, "nothing rests at eToro")
        self.trade = row
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3))
        self._assert_marked_and_stopped(self._tick())


class TheMarksBeforeProposalsTests(_BudgetOn, TestCase):
    """The marks keep real room over the proposals (2026-11-01, review):
    FLOOR_P4 0.40, so a proposal leaves 24 of 60 market tokens and the
    marks keep 18 a minute the proposals cannot take. The fleet tick works
    one config at a time, manage then propose, so in a minute the bar pass
    already holds its half of, an earlier config's proposals took the room
    a later config's marks needed (at FLOOR_P4 0.20 only 6 were left), and
    entries were asked while the care of open rows waited."""

    SYMS_A = [f"PA{i:02d}" for i in range(18)]     # config A's proposals
    SYMS_B = [f"MB{i:02d}" for i in range(15)]     # config B's open rows

    def setUp(self):
        super().setUp()
        from bot_program.models import AssetBotConfig
        from tests.test_exit_truth import _trade, _user
        user = _user("budget_order")
        self.cfg_a, self.cfg_b = (AssetBotConfig.objects.create(
            user=user, asset_class="stock", name=name, mode="live",
            symbols=list(symbols), capital=Decimal("10000"), enabled=True)
            for name, symbols in (("A research", self.SYMS_A),
                                  ("B manual", [])))
        for s in self.SYMS_B:
            # eToro holds each one's stop: the marks are P3
            _trade(self.cfg_b, symbol=s, metadata={
                "initial_stop_loss": 98.0, "protected": True,
                "broker": "etoro", "broker_env": "live"})
        self.t, self.fake = _client([RATES_OK], env="live")
        for i, s in enumerate(self.SYMS_A + self.SYMS_B):
            self.t._ids[s] = 7000 + i
            self.t._symbols[7000 + i] = s
            self.t._venue_spelling[7000 + i] = s

    def test_the_bar_pass_and_an_earlier_configs_proposals_leave_the_marks(
            self):
        from bot_program.asset_engine import runner, skips
        from bot_program.asset_engine.base import BotDecision
        from bot_program.models import AssetBotConfig
        for _ in range(eb.limit(eb.MARKET, eb.P5)):      # the bar pass's half
            eb.take(KH, eb.MARKET, eb.P5, world="live", where="candles")
        seen = []
        real = eb.take

        def take(kh, family, priority, **kw):
            try:
                real(kh, family, priority, **kw)
            except eb.Refused:
                seen.append((family, int(priority), "refused"))
                raise
            seen.append((family, int(priority), "granted"))
        decision = BotDecision(direction="BUY", score=0.9, reasons=["t"],
                               rule_name="budget_rule")
        candidates = []
        with mock.patch(ROUTER, return_value=self.t), \
                mock.patch("bot_program.asset_engine.stock_bot.StockBot"
                           ".decide", return_value=decision), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           ".can_open_new", return_value=(True, "")), \
                mock.patch.object(eb, "take", take):
            configs = list(AssetBotConfig.objects.filter(enabled=True))
            self.assertEqual([c.name for c in configs],
                             ["A research", "B manual"])
            for cfg in configs:
                runner._propose_phase(cfg, signal_stats={},
                                      candidates=candidates,
                                      not_desked={"paper": [], "live": []},
                                      summaries=[])

        def n(p, what):
            return sum(1 for s in seen if s == ("market", p, what))
        self.assertEqual((n(eb.P3, "granted"), n(eb.P3, "refused")), (15, 0),
                         "every open row's mark was read")
        self.assertEqual((n(eb.P4, "granted"), n(eb.P4, "refused")), (6, 12),
                         "the proposals were deferred instead")
        self.assertEqual(len(candidates), 6)
        notes = skips.last_by_symbol(self.cfg_b)
        self.assertFalse([s for s, note in notes.items()
                          if "the mark was not asked" in str(
                              note.get("detail"))], notes)


class TheProposalTests(_BudgetOn, TestCase):

    def setUp(self):
        super().setUp()
        from tests.test_entry_quote import (_account, _book, _instrument,
                                            _live_cfg, _signal, _user)
        self.user = _user("budget_prop")
        self.cfg = _live_cfg(self.user, name="BP")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="bp_rule")
        _book(self.user)
        _account(self.user, cash=100000)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)

    def test_a_refused_proposal_records_a_skip_and_asks_nothing(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P4))
        t, fake = _client([SEARCH_AAPL, RATES_OK])
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNone(StockBot(self.cfg).propose_entry("AAPL"))
        self.assertEqual(fake.calls, [])
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertEqual(note["detail"],
                         "eToro budget: market 36/60 this minute, 24 kept "
                         "for higher priorities (P4 proposal) — not asked")
        self.assertEqual(vh._load(vh._key("etoro", "demo")), {})

    def test_a_proposal_with_room_reads_its_rate_at_p4(self):
        from bot_program.asset_engine.stock_bot import StockBot
        t, fake = _client([SEARCH_AAPL, RATES_OK])
        with mock.patch(ROUTER, return_value=t):
            StockBot(self.cfg).propose_entry("AAPL")
        self.assertEqual(len(_wire_calls(fake, "/rates")), 1)
        self.assertEqual(cache.get(eb._p_key(KH, eb.MARKET, eb.window(),
                                             eb.P4)), 2, "/search + /rates")


# ── the bars: P5, the public feed on a refusal, never a mute ──────────────

class _RowsFeed:
    """The keyless feed, with two bars for every series."""
    _sv_public_feed = True

    def __init__(self):
        self.calls = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval))
        now = int(timezone.now().timestamp() * 1000) // 3_600_000 * 3_600_000
        return [[now - 3_600_000 * i, "1.1", "1.2", "1.0", "1.15", "5",
                 now - 3_600_000 * i + 3_600_000, "0", 0, "0", "0", "0"]
                for i in (1, 0)]


def _bars_base():
    from tests.test_bars_etoro_quota import _Base
    return _Base


class TheBarsTests(_BudgetOn, _bars_base()):
    """The quota module's pass (tests.test_bars_etoro_quota._Base): its
    EtoroTrader is keyed "u", its clock is the pass's own."""

    KU = eb.key_hash("u")

    def setUp(self):
        super().setUp()
        self.feed = _RowsFeed()

    def _feed_tag(self):
        from market_data.bot_bars import _source_tag
        tag = _source_tag(self.feed)
        self.assertTrue(tag.endswith("_public"), tag)
        return tag

    def _sources(self, symbol):
        from market_data.models import PriceData
        return set(PriceData.objects.filter(instrument__symbol=symbol)
                   .values_list("source", flat=True))

    def test_a_live_configs_series_is_read_from_etoro(self):
        self._cfg(["EURUSD"], mode="live", name="L")
        self._run()
        self.assertEqual(len(self.wire.candle_calls()), 2)
        self.assertEqual(self.feed.calls, [])
        self.assertEqual(self._sources("EURUSD"), {"etoro"})
        self.assertEqual(cache.get(eb._p_key(self.KU, eb.MARKET, eb.window(),
                                             eb.P5)), 3, "/search + 2 x "
                                                         "/candles at P5")

    def test_a_refused_take_falls_back_to_the_public_feed_and_mutes_nothing(
            self):
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        self._cfg(["EURUSD"], mode="live", name="L")
        out = self._run()
        self.assertEqual(self.wire.calls, [], "not a request sent")
        self.assertEqual(self.feed.calls, [("EURUSD", "4h"),
                                           ("EURUSD", "1h")])
        self.assertEqual(self._sources("EURUSD"), {self._feed_tag()})
        for interval in ("4h", "1h"):
            self.assertIsNone(cache.get(f"bars:mute:etoro:EURUSD:{interval}"),
                              "a refused take never mutes the venue")
        self.assertEqual(out["errors"], 0, "not a failure")
        self.assertEqual(out["fallback"], 2)
        self.assertEqual(out["etoro_asked"], 0)
        self.assertEqual(out["etoro_left"], 2)
        self.assertIn("eToro budget: market 30/60 this minute",
                      out["etoro_stopped"])
        self.assertEqual(vh._load(vh._key("etoro", "live")), {})

    def test_a_paper_research_series_comes_from_the_public_feed_when_p5_is_short(
            self):
        # three tokens left under P5: the live config's /search and its
        # two series take them; the paper config's series find none
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5) - 3)
        self._cfg(["EURUSD"], name="A paper")
        self._cfg(["USDJPY"], mode="live", name="Z live")
        self._run()
        calls = self.wire.candle_calls()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("/instruments/1002/" in u for u in calls), calls)
        self.assertEqual(self._sources("USDJPY"), {"etoro"})
        self.assertEqual(self.feed.calls, [("EURUSD", "4h"),
                                           ("EURUSD", "1h")])
        self.assertEqual(self._sources("EURUSD"), {self._feed_tag()})
        self.assertIsNone(cache.get("bars:mute:etoro:EURUSD:4h"))

    def test_the_pass_asks_etoro_again_in_the_next_window(self):
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        self._cfg(["EURUSD"], mode="live", name="A")
        self._cfg(["USDJPY"], mode="live", name="B")
        seen = {"n": 0}

        def client_for(*a, **k):
            seen["n"] += 1
            if seen["n"] == 2:
                # the next minute, for the pass and for the budget
                self.clock.t += 61
                self.bclock.t += 61
            return self._client()
        self._run(client_for=client_for)
        calls = self.wire.candle_calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(all("/instruments/1002/" in u for u in calls), calls)
        self.assertEqual(self._sources("EURUSD"), {self._feed_tag()})
        self.assertEqual(self._sources("USDJPY"), {"etoro"})

    def _next_minute_at(self, n_client):
        """A client_for that moves the pass and the budget into the next
        minute before its `n_client`-th client."""
        seen = {"n": 0}

        def client_for(*a, **k):
            seen["n"] += 1
            if seen["n"] == n_client:
                self.clock.t += 61
                self.bclock.t += 61
            return self._client()
        return client_for

    def test_after_a_live_series_was_refused_no_paper_series_reads_etoro(
            self):
        """2026-11-01, review: P5 is spent in minute M, live A's EURUSD is
        refused (the public feed), and paper Z's USDJPY is reached in M+1,
        when P5 has tokens again. Paper never takes, in that pass, the
        eToro token a live series went without: it reads the public feed
        too, and nothing is muted."""
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["USDJPY"], name="Z paper")
        out = self._run(client_for=self._next_minute_at(2))
        self.assertEqual(self.wire.calls, [], "eToro asked nothing")
        self.assertEqual(self._sources("EURUSD"), {self._feed_tag()})
        self.assertEqual(self._sources("USDJPY"), {self._feed_tag()})
        self.assertIsNone(cache.get("bars:mute:etoro:USDJPY:4h"))
        self.assertEqual(out["errors"], 0)
        self.assertIn("2 paper or Orc series not asked after a live series "
                      "was refused", out["etoro_stopped"])

    def test_a_paper_series_on_the_same_keys_demo_world_is_held_back_too(
            self):
        """One key opens both worlds and spends one budget: a paper config
        whose bars come from the key's demo world gets no token a live
        series of the live world went without."""
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["USDJPY"], name="Z paper")
        live_first = self._next_minute_at(2)

        def client_for(*a, **k):
            t = live_first(*a, **k)
            if self.clock.t > 1000.0:          # the paper config's: demo
                t = ec.EtoroTrader("k", "u", env="demo")
                t._session = self.wire
            return t
        self._run(client_for=client_for)
        self.assertEqual(self.wire.calls, [], "eToro asked nothing")
        self.assertEqual(self._sources("USDJPY"), {self._feed_tag()})

    def test_a_held_real_rows_refused_series_holds_paper_back_too(self):
        self._pin_silver()
        self._held(enabled=True)
        self._cfg(["USDJPY"], name="Z paper")
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        self._run(client_for=self._next_minute_at(2))
        self.assertEqual(self.wire.candle_calls(), [])
        self.assertEqual(self._sources("XAGUSD"), {self._feed_tag()})
        self.assertEqual(self._sources("USDJPY"), {self._feed_tag()})

    def test_a_later_live_series_still_reads_etoro_after_the_refusal(self):
        _fill(self.KU, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["USDJPY"], mode="live", name="B live")
        self._cfg(["GBPUSD"], name="Z paper")
        self._run(client_for=self._next_minute_at(2))
        self.assertEqual(self._sources("EURUSD"), {self._feed_tag()})
        self.assertEqual(self._sources("USDJPY"), {"etoro"})
        self.assertEqual(self._sources("GBPUSD"), {self._feed_tag()})
        self.assertTrue(all("/instruments/1002/" in u
                            for u in self.wire.candle_calls()))

    def test_with_no_live_series_refused_paper_reads_etoro_from_spare(self):
        self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["USDJPY"], name="Z paper")
        self._run()
        self.assertEqual(self._sources("EURUSD"), {"etoro"})
        self.assertEqual(self._sources("USDJPY"), {"etoro"})


# ── the sync and the re-read: deferred, never a miss ──────────────────────

class TheAccountReadTests(_BudgetOn, TestCase):

    def setUp(self):
        super().setUp()
        from tests.test_sync_walks_etoro import _etoro
        self.user = User.objects.create_user("budget_sync", password="x")
        self.acct = _etoro(self.user, demo=False, is_primary_for_stocks=True)
        self.t = ec.EtoroTrader("k", "u", env="live")
        self.t._session = _FakeSession([
            ("GET", "/aggregate-portfolio", 200, {
                "accountCurrency": "USD", "accountTotals": {
                    "accountTotalValue": 1000.0,
                    "accountAvailableCash": 400.0,
                    "accountTotalUsedMargin": 600.0}}),
            ("GET", "/portfolio", 200, {"positions": []})])
        _fill(eb.key_hash("u"), eb.ACCOUNT, eb.limit(eb.ACCOUNT, eb.P2))

    def test_a_refused_sync_read_defers_the_account_and_counts_no_miss(self):
        from bot_program.models import EtoroAccount
        from bot_program.tasks import sync_etoro_accounts
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                        return_value=self.t), \
                mock.patch("bot_program.notifications.notify_staff") as told:
            out = sync_etoro_accounts.__wrapped__.__wrapped__()
        self.assertEqual(self.t._session.calls, [])
        self.assertEqual((out["attempted"], out["stored"], out["unreachable"],
                          out["deferred"]), (0, 0, 0, 1))
        # not a run of the component: the gate's `idle`, never a status it
        # would judge (a "skipped" status reads as success on the shared
        # row: TheDeferredSyncVerdictTests)
        self.assertNotIn("status", out)
        self.assertTrue(out["idle"].startswith(
            "the eToro request budget deferred 1 account read(s) to the next "
            "pass"), out["idle"])
        self.assertEqual(out["reason"], out["idle"])
        self.assertIsNone(cache.get(f"broker_sync:miss:etoro:{self.acct.pk}"))
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertIsNone(acct.last_margin_at)
        self.assertIsNone(acct.last_sync)
        told.assert_not_called()

    def test_a_refused_re_read_writes_nothing_and_says_not_asked(self):
        from bot_program.models import EtoroAccount
        from bot_program.tasks import refresh_etoro_cells
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                        return_value=self.t), \
                mock.patch("core.platform_control.is_component_enabled",
                           return_value=True):
            out = refresh_etoro_cells(self.acct.pk, why="after a close")
        self.assertEqual(self.t._session.calls, [])
        self.assertFalse(out["read"])
        self.assertTrue(out["skipped"].startswith(
            "not asked: eToro budget: account 28/30 this minute"),
            out["skipped"])
        self.assertIsNone(EtoroAccount.objects.get(
            pk=self.acct.pk).last_margin_at)


def _components_only():
    from tests.test_component_digest import _ComponentsOnly
    return _ComponentsOnly


class TheDeferredSyncVerdictTests(_BudgetOn, _components_only()):
    """A sync pass the budget deferred whole is NOT A RUN of the shared
    broker_account_sync row (2026-11-01, review): it answers the gate's
    `idle` (core/task_gate.guarded_task), and the row keeps the verdict of
    the last pass that read an account. Its "skipped" status was judged a
    success: an eToro error on the row three walks share turned green."""

    def setUp(self):
        super().setUp()
        from tests.test_component_digest import _component
        from tests.test_sync_walks_etoro import _etoro
        _component("platform_master", category="system")
        _component("broker_account_sync", category="pipeline")
        user = User.objects.create_user("budget_verdict", password="x")
        _etoro(user, demo=False, is_primary_for_stocks=True)

    def _row(self):
        from core.platform_control import PlatformComponent
        row = PlatformComponent.objects.get(key="broker_account_sync")
        return (row.last_status, row.last_message, row.run_count,
                row.error_count, row.last_run_at)

    def _gated(self, client):
        from bot_program.tasks import sync_etoro_accounts
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                        return_value=client), \
                mock.patch("bot_program.notifications.notify_staff"):
            return sync_etoro_accounts.__wrapped__()       # through the gate

    def test_an_etoro_error_stays_an_error_through_a_deferred_pass(self):
        from bot_program.models import EtoroAccount
        from core.component_digest import collect_faults
        with mock.patch.object(EtoroAccount.objects, "exclude",
                               side_effect=RuntimeError("eToro answered "
                                                        "500")), \
                self.assertRaises(RuntimeError):
            self._gated(mock.MagicMock())
        before = self._row()
        self.assertEqual(before[0], "error")
        t = ec.EtoroTrader("k", "u", env="live")
        t._session = _FakeSession([])
        _fill(eb.key_hash("u"), eb.ACCOUNT, eb.limit(eb.ACCOUNT, eb.P2))
        out = self._gated(t)
        self.assertEqual(t._session.calls, [])
        self.assertEqual((out["attempted"], out["deferred"]), (0, 1))
        self.assertEqual(self._row(), before, "the row keeps its verdict")
        self.assertEqual([f["key"] for f in collect_faults()["errors"]],
                         ["broker_account_sync"])

    def test_a_pass_that_read_an_account_is_still_judged(self):
        t = ec.EtoroTrader("k", "u", env="live")
        t._session = _FakeSession([
            ("GET", "/aggregate-portfolio", 200, {
                "accountCurrency": "USD", "accountTotals": {
                    "accountTotalValue": 1000.0,
                    "accountAvailableCash": 400.0,
                    "accountTotalUsedMargin": 600.0}}),
            ("GET", "/portfolio", 200, {"positions": []})])
        out = self._gated(t)
        self.assertNotIn("idle", out)
        self.assertEqual(self._row()[0], "success")


# ── the P2 sites: an account read the budget defers is never a failure ────

#: an account's aggregate and its book, as eToro answers them
AGG = ("GET", "/aggregate-portfolio", 200, {
    "accountCurrency": "USD", "accountTotals": {
        "accountTotalValue": 1000.0, "accountAvailableCash": 400.0,
        "accountTotalUsedMargin": 600.0}})
EMPTY_BOOK = ("GET", "/portfolio", 200, {"positions": []})
AAPL_BOOK = ("GET", "/portfolio", 200, {"positions": [
    {"instrumentID": 1001, "units": 1.0, "isBuy": True, "positionID": 999}]})


def _account_at_p2s_limit(kh=KH):
    _fill(kh, eb.ACCOUNT, eb.limit(eb.ACCOUNT, eb.P2))


class TheReconcileTests(_BudgetOn, TestCase):
    """reconcile_user and reconcile_unknown_positions are P2 (2026-11-01):
    a book the budget did not read is "broker unavailable" for the pass —
    nothing sent, nothing booked CLOSED — and said as not asked."""

    def setUp(self):
        super().setUp()
        from tests.test_reconcile_by_id import _cfg, _trade
        self.user = User.objects.create_user("budget_rc", password="x")
        self.cfg = _cfg(self.user, asset_class="stock", name="st")
        self.cfg.symbols = ["AAPL"]
        self.cfg.save(update_fields=["symbols"])
        self._trade = _trade

    def _run(self, t, fn):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return fn(self.user)

    def test_the_account_family_spent_reads_no_book_and_closes_nothing(self):
        from bot_program import reconcile_asset
        trade = self._trade(self.cfg, symbol="AAPL", pid="555")
        _account_at_p2s_limit()
        t, fake = _client([SEARCH_AAPL, EMPTY_BOOK,
                           ("GET", "orders:lookup", 200, CLOSED)], env="live")
        with self.assertLogs("bot_program.reconcile_asset",
                             level="INFO") as logs:
            out = self._run(t, reconcile_asset.reconcile_user)
        self.assertEqual(_wire_calls(fake, "/portfolio"), [], fake.calls)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual((out["closed_as_orphan"], out["broker_unavailable"]),
                         (0, 1), out)
        self.assertTrue(any("get_positions() not asked: eToro budget: "
                            "account" in ln for ln in logs.output),
                        logs.output)
        self.assertFalse([ln for ln in logs.output
                          if ln.startswith("WARNING")
                          and "get_positions()" in ln], logs.output)

    def test_a_refused_name_warm_leaves_the_row_open(self):
        from bot_program import reconcile_asset
        trade = self._trade(self.cfg, symbol="AAPL", pid="")
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P2))
        t, fake = _client([SEARCH_AAPL, AAPL_BOOK], env="live")
        out = self._run(t, reconcile_asset.reconcile_user)
        self.assertEqual(_wire_calls(fake, "/search"), [], fake.calls)
        self.assertEqual(len(_wire_calls(fake, "/portfolio")), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["broker_unavailable"], 1, out)

    def test_the_unclaimed_sweep_reads_no_book(self):
        from bot_program import reconcile_asset
        _account_at_p2s_limit()
        t, fake = _client([SEARCH_AAPL, AAPL_BOOK], env="live")
        out = self._run(t, reconcile_asset.reconcile_unknown_positions)
        self.assertEqual(_wire_calls(fake, "/portfolio"), [], fake.calls)
        self.assertEqual((out["broker_unavailable"], out["unclaimed"]),
                         (1, 0), out)


class TheOtherAccountReadersTests(_BudgetOn, TestCase):
    """The pool check, the /brokers/ probe, the legacy /setup/ adapter,
    Telegram /status and the digest: each says a read the budget did not
    send as not asked, and sends nothing."""

    def test_the_pool_check_answers_not_measured(self):
        from bot_program import capital_truth
        from tests.test_reconcile_by_id import _cfg
        user = User.objects.create_user("budget_pc", password="x")
        cfg = _cfg(user, asset_class="stock", name="pc")
        cfg.symbols = ["AAPL"]
        cfg.extras = {}
        cfg.save(update_fields=["symbols", "extras"])
        _account_at_p2s_limit()
        t, fake = _client([AGG], env="live")
        with mock.patch(ROUTER, return_value=t):
            self.assertIsNone(capital_truth.broker_equity(user, cfg))
        self.assertEqual(fake.calls, [])

    def test_the_key_probe_answers_unknown_in_the_budgets_words(self):
        from dashboard import views_brokers
        _account_at_p2s_limit()
        with mock.patch("requests.get") as get:
            state, words = views_brokers.etoro_probe("api-k", "user-k",
                                                     demo=False)
        get.assert_not_called()
        self.assertEqual(state, "unknown")
        self.assertTrue(words.startswith("eToro budget: account 28/30"),
                        words)

    def test_the_legacy_adapter_answers_as_a_failed_fetch(self):
        from market_data.adapters.etoro_adapter import EtoroClient
        c = EtoroClient(api_key="legacy-k")
        _account_at_p2s_limit(eb.key_hash("legacy-k"))
        with mock.patch.object(c.session, "get") as get:
            self.assertIsNone(c.get_positions())
            self.assertIsNone(c.get_portfolio())
            self.assertIsNone(c.get_account_balance())
        get.assert_not_called()

    def test_telegram_status_says_not_read_now(self):
        from bot_program import telegram_eye

        class _Acct:
            api_key_enc = "stored"
            user_id = 0

            def get_credentials(self):
                return "api-k", "user-k"
        _account_at_p2s_limit()
        t, fake = _client([AGG, EMPTY_BOOK], env="live")
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                        return_value=t):
            lines = telegram_eye._live_lines(_Acct())
        self.assertEqual(fake.calls, [])
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("Live account: not read now"),
                        lines)

    def test_the_digest_says_the_live_read_was_not_asked(self):
        from alerts import digest_book
        from bot_program.models import EtoroAccount
        user = User.objects.create_user("budget_dg", password="x")
        acct = EtoroAccount.objects.create(user=user)
        acct.set_credentials("api-k", "user-k")
        acct.save()
        _account_at_p2s_limit()
        t, fake = _client([AGG, EMPTY_BOOK], env="live")
        with mock.patch("bot_program.engine.etoro_client.EtoroTrader",
                        return_value=t):
            lines, facts = digest_book.real_account(acct, timezone.now())
        self.assertEqual(fake.calls, [])
        self.assertEqual(facts.get("why"), digest_book.READ_DEFERRED,
                         (lines, facts))


# ── the legacy BotConfig lane: its candle read is P5 ──────────────────────

class TheLegacyLaneTests(_BudgetOn, TestCase):
    """engine/runner.run_bot_tick ("Run tick now") sets no scope: its
    tickers are P1, and its entry scan's candle read is P5 (klines). A
    refused candle read is a skip said at INFO (2026-11-01, review), never
    "scan fail" at ERROR with a traceback: nothing was sent, no entry is
    scored, and nothing is noted on the venue's health."""

    CANDLES = ("GET", "/history/candles", 200, {"candles": [{
        "instrumentId": 1001, "candles": [
            {"fromDate": f"2026-10-0{1 + i // 24}T{i % 24:02d}:00:00Z",
             "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1.0} for i in range(60)]}]})

    def setUp(self):
        super().setUp()
        from bot_program.models import BotConfig
        self.user = User.objects.create_user("budget_legacy", password="x")
        BotConfig.objects.create(user=self.user, enabled=True, mode="live",
                                 symbols=["AAPL"],
                                 capital_usdt=Decimal("1000"))

    def _tick(self, t):
        from bot_program.engine import runner
        from bot_program.engine.strategy import Decision
        hold = Decision(symbol="AAPL", score=0.0, confidence=0.0,
                        direction="HOLD", reasons=["t"], sl_pct=1.5,
                        tp_pct=3.0)
        with mock.patch.object(runner, "client_for_symbol", return_value=t), \
                mock.patch.object(runner, "broker_name_for_symbol",
                                  return_value="etoro"), \
                mock.patch.object(runner, "decide", return_value=hold):
            runner.run_bot_tick(self.user.id)

    def test_a_refused_candle_read_is_a_skip_said_at_info(self):
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        t, fake = _client([SEARCH_AAPL, self.CANDLES, RATES_OK], env="live")
        with self.assertLogs("bot_program.engine.runner",
                             level="INFO") as logs:
            self._tick(t)
        self.assertEqual([c for c in fake.calls if "/history/candles" in c[1]
                          or "/market-data/search" in c[1]], [])
        self.assertFalse([r for r in logs.records
                          if r.levelname in ("ERROR", "WARNING")],
                         logs.output)
        self.assertTrue(any(r.levelname == "INFO" and r.getMessage().startswith(
            "scan AAPL: not asked — eToro budget: market 30/60")
            for r in logs.records), logs.output)
        self.assertEqual(vh._load(vh._key("etoro", "live")), {})

    def test_with_room_the_candle_read_goes(self):
        t, fake = _client([SEARCH_AAPL, self.CANDLES, RATES_OK], env="live")
        self._tick(t)
        self.assertTrue(_wire_calls(fake, "/history/candles"))


# ── the ramp and the smoke: P5, said, never a failure ─────────────────────

class TheToolsTests(_BudgetOn, SimpleTestCase):

    def test_the_headroom_ramp_stops_at_a_refusal_and_measures_nothing(self):
        from market_data import candle_headroom
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        t, fake = _client([SEARCH_AAPL], env="demo")
        with mock.patch.object(candle_headroom, "_sleep"):
            res = candle_headroom.run(t, ["AAPL"], max_requests=4)
        self.assertEqual(fake.calls, [])
        self.assertEqual(res["requests"], 0)
        self.assertFalse(res["hit_429"])
        self.assertTrue(res["aborted"].startswith(
            "the eToro budget refused a candle read (eToro budget: market "
            "30/60"), res["aborted"])

    def test_the_smoke_names_a_refusal_as_not_asked(self):
        from bot_program.management.commands import etoro_smoke
        err = eb.Refused(eb.MARKET, eb.P5, eb.FLOOR, "eToro budget: x")

        def refused():
            raise err
        self.assertEqual(etoro_smoke._verdict(refused),
                         (etoro_smoke.UNKNOWN, "eToro budget: x — not asked"))


# ── the read-only command ─────────────────────────────────────────────────

class TheCommandTests(_BudgetOn, SimpleTestCase):

    def test_it_prints_per_key_hash_and_family_and_never_the_key(self):
        secret = "SECRET-USER-KEY-0042"
        kh = eb.key_hash(secret)
        _fill(kh, eb.MARKET, 30)
        with self.assertRaises(eb.Refused):
            eb.take(kh, eb.MARKET, eb.P5, world="live", where="candles")
        _fill(kh, eb.EXECUTION, 21, priority=eb.P0)
        t = ec.EtoroTrader("api-k", secret, env="live")
        from tests.test_etoro_rate_pause import _HSession
        t._session = _HSession([SEARCH_AAPL[:4],
                                RATES_429 + ({"Retry-After": "40"},)])
        with self.assertRaises(Exception):
            t.ticker("AAPL")
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        text = out.getvalue()
        self.assertNotIn(secret, text)
        self.assertIn(f"key {kh}", text)
        self.assertIn("market", text)
        self.assertIn("P5 refused 1 (floor)", text)
        self.assertIn("overruns 1", text)
        self.assertIn("429 pause: live holds for 40 s", text)
        self.assertIn("demo none", text)

    def test_it_prints_the_rolling_minute_a_take_is_judged_on(self):
        # 2026-11-02 (completes E1): 30 at a minute's last second, read 2 s
        # later in the next minute, whose own count is 0
        self.bclock.t += 59
        _fill(KH, eb.MARKET, 30)
        self.bclock.t += 2
        self.assertEqual(eb.report()["keys"][KH]["rolling"][eb.MARKET], 30)
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        self.assertIn("market     in the last 60 s: 30/60 (what a take is "
                      "judged on)", out.getvalue())

    def test_it_says_when_nothing_was_counted(self):
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        self.assertIn("No eToro request has been counted", out.getvalue())

    def test_it_is_registered_read_only_and_terminal_only(self):
        from core import ops_commands
        e = ops_commands.get("etoro_budget")
        self.assertTrue(e["read_only"])
        self.assertEqual(e["category"], "read")
        self.assertFalse(ops_commands.is_runnable(e))
        self.assertNotIn("etoro_budget", ops_commands.runnable_names())


# ── the key, nowhere ──────────────────────────────────────────────────────

class TheKeyIsNowhereTests(_BudgetOn, SimpleTestCase):

    def test_the_key_is_in_no_cache_key_and_no_log_line(self):
        secret = "SECRET-USER-KEY-0042"
        kh = eb.key_hash(secret)
        self.assertEqual(len(kh), 12)
        self.assertNotIn(secret, kh)
        from tests.test_etoro_rate_pause import _HSession
        # the app's logger: every line of the adapter, the budget, the
        # venue's memory and the command lands there (core/logging_config:
        # the apps do not propagate to the root)
        with self.assertLogs("bot_program", level="DEBUG") as logs:
            t = ec.EtoroTrader("api-k", secret, env="live")
            t._session = _HSession([SEARCH_AAPL[:4],
                                    RATES_429 + ({"Retry-After": "40"},)])
            with self.assertRaises(Exception):
                t.ticker("AAPL")                       # a pause, noted
            with eb.at(eb.P3), self.assertRaises(eb.Refused):
                t.ticker("AAPL")                       # refused: the pause
            _fill(kh, eb.MARKET, 61, priority=eb.P0)   # an overrun, logged
            with eb.at(eb.P5), self.assertRaises(eb.Refused):
                eb.take(kh, eb.MARKET, eb.P5, where="candles")
            with mock.patch.object(eb, "_cache", return_value=_Down()):
                eb.spend(kh, eb.MARKET, eb.P0, where="close")
            call_command("etoro_budget", stdout=StringIO())
        keys = list(cache._cache.keys())
        self.assertTrue(any(kh in k for k in keys), keys)
        for k in keys:
            self.assertNotIn(secret, k)
        self.assertTrue(logs.output)
        for line in logs.output:
            self.assertNotIn(secret, line)
        self.assertTrue(any(kh in line for line in logs.output))


class TheErrorsTests(SimpleTestCase):
    """A refusal is no requests error and no 429: the bar pass and the
    last look read neither off it."""

    def test_a_refusal_carries_no_response(self):
        from market_data.bot_bars import _http_status
        e = eb.Refused(eb.MARKET, eb.P5, eb.FLOOR, "eToro budget: x")
        self.assertIsNone(_http_status(e))
        self.assertNotIsInstance(e, requests.RequestException)
