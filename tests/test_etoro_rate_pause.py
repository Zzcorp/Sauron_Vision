"""THE 429 PAUSE and THE /search "NO" (2026-10-07).

On 2026-10-06 eToro's live world went SICK at 23:38:34 UTC on seven /search
429s in one second, most likely asked by the bar refresh, and stayed held
with words that read "0 failures in the last 3 min" and "?" for every time.

  * after a 429 on a trading-lane read (/rates or /search), THIS PROCESS
    grants itself one short pause per world (Retry-After, capped at 120 s;
    30 s with none). The entry side (propose, execute, the last look) does
    not ask while it runs; the manage tick's marks, closes and the manual
    lane never read it. A world refused again within 450 s of its last
    pause's end gets none, so SICK stays reachable.
  * a BACKGROUND read (klines, for the bar refresh: its candles and the
    /search a cold id costs) goes through the same bounded read, but notes
    nothing on the venue's health and grants no pause.
  * eToro's own "no such instrument" to /search, said twice a minute or
    more apart, is kept for six hours per (world, symbol); a refusal never.

The entry side's holds are pinned in tests/test_entry_holds.py.

Run with:  python manage.py test tests.test_etoro_rate_pause
"""
from unittest import mock

import requests
from django.test import SimpleTestCase

from bot_program import venue_health as vh
from bot_program.engine import etoro_client as ec
from tests.test_etoro_client import (SEARCH_AAPL, _clear_eligibility, _client,
                                     _FakeSession, _Resp)

RATES_OK = ("GET", "/rates", 200, {"rates": [
    {"bid": 99.9, "ask": 100.1, "lastExecution": 100.0}]})
RATES_429 = ("GET", "/rates", 429, {"message": "Too Many Requests"})
SEARCH_429 = ("GET", "/market-data/search", 429, {})
SEARCH_NONE = ("GET", "/market-data/search", 200, [])
CANDLES_429 = ("GET", "/history/candles", 429, {})


class _HResp(_Resp):
    """A response with headers, raising as requests does (with .response)."""

    def __init__(self, status, payload=None, headers=None):
        super().__init__(status, payload)
        self.headers = dict(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error",
                                     response=self)


class _HSession(_FakeSession):
    """Routes (method, sub, status, payload[, headers])."""

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for route in self.routes:
            m, sub, status, payload = route[:4]
            if m == method and sub in url:
                return _HResp(status, payload,
                              route[4] if len(route) > 4 else None)
        return _HResp(*self.default)


class _SeqHSession(_HSession):
    """_HSession whose answers come in ORDER per (method, url-substring):
    each step is (status, payload[, headers]); the last one repeats.
    Everything else falls through to the routes."""

    def __init__(self, seqs, routes=None):
        super().__init__(routes)
        self.seqs = {k: list(v) for k, v in seqs.items()}

    def _hit(self, method, url, **kw):
        for (m, sub), seq in self.seqs.items():
            if m == method and sub in url:
                self.calls.append((method, url, kw))
                step = seq.pop(0) if len(seq) > 1 else seq[0]
                return _HResp(*step)
        return super()._hit(method, url, **kw)


def _hclient(routes, env="live"):
    t = ec.EtoroTrader("api-k", "user-k", env=env)
    t._session = _HSession(routes)
    return t, t._session


def _sclient(seqs, routes=(), env="live"):
    t = ec.EtoroTrader("api-k", "user-k", env=env)
    t._session = _SeqHSession(seqs, routes=list(routes))
    return t, t._session


def _calls(fake, sub):
    return [c for c in fake.calls if sub in c[1]]


def _candles(n=3, iid=1001):
    """eToro's measured candle shape: one group, the bars one level down."""
    bars = [{"fromDate": f"2026-10-06T{4 * i:02d}:00:00Z", "open": 1.1,
             "high": 1.2, "low": 1.0, "close": 1.15, "volume": 5}
            for i in range(n)]
    return {"candles": [{"instrumentId": iid, "candles": bars}]}


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class _PauseOn:
    def setUp(self):
        super().setUp()
        for name, value in (("RATE_PAUSE", True), ("SEARCH_NO_MEMO", True)):
            p = mock.patch.object(ec, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.clock = _Clock()
        p = mock.patch.object(ec, "_mono", self.clock)
        p.start()
        self.addCleanup(p.stop)
        ec._RATE_PAUSE.clear()
        ec._SEARCH_NO.clear()
        self.addCleanup(ec._RATE_PAUSE.clear)
        self.addCleanup(ec._SEARCH_NO.clear)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)


# ── the switches ──────────────────────────────────────────────────────────

class TheSwitchTests(SimpleTestCase):
    """Outside _PauseOn (2026-10-07, review): inside it both switches are
    patched on, so a test there could read only the source of
    tests/__init__.py — a later line or a leaking module that left either
    on would pass it, and the pause and the kept "no" would leak between
    tests."""

    def test_the_suite_runs_with_both_off(self):
        self.assertIs(ec.RATE_PAUSE, False)
        self.assertIs(ec.SEARCH_NO_MEMO, False)
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_client.RATE_PAUSE = False", src)
        self.assertIn("_etoro_client.SEARCH_NO_MEMO = False", src)


# ── the pause, at the adapter ─────────────────────────────────────────────

class ThePauseTests(_PauseOn, SimpleTestCase):

    def _refuse(self, t):
        with self.assertRaises(Exception):
            t.ticker("AAPL")

    def test_the_constants(self):
        self.assertEqual((ec.RATE_PAUSE_FALLBACK_S, ec.RATE_PAUSE_MAX_S,
                          ec.RATE_PAUSE_STREAK_S), (30.0, 120.0, 450.0))
        self.assertEqual(ec.RATE_PAUSE_SITES,
                         frozenset({"ticker", "search"}))
        self.assertEqual((ec.SEARCH_NO_CONFIRM_S, ec.SEARCH_NO_TTL_S),
                         (60.0, 21600.0))

    def test_a_429_with_retry_after_pauses_this_world_for_that_long(self):
        t, fake = _hclient([SEARCH_AAPL[:4],
                            RATES_429 + ({"Retry-After": "12"},)])
        self._refuse(t)
        self.assertEqual(t.rate_pause_s(), 12.0)
        other, _ = _hclient([], env="demo")
        self.assertEqual(other.rate_pause_s(), 0.0, "worlds never share")
        self.clock.t += 5
        self.assertEqual(t.rate_pause_s(), 7.0)
        state = vh._load(vh._key("etoro", "live"))
        self.assertEqual(len(state["failures"]), 1, "still noted, once")
        self.assertEqual(len(_calls(fake, "/rates")), 1, "never retried")
        self.assertIn("Retry-After 12; paused 12s",
                      state["failures"][0]["detail"])

    def test_no_header_pauses_for_the_fallback_and_the_note_says_so(self):
        t, _ = _hclient([SEARCH_AAPL[:4], RATES_429])
        self._refuse(t)
        self.assertEqual(t.rate_pause_s(), 30.0)
        f = vh._load(vh._key("etoro", "live"))["failures"][-1]
        self.assertEqual(f["code"], 429)
        self.assertTrue(f["detail"].startswith("no Retry-After; paused 30s"),
                        f)

    def test_a_huge_a_garbage_or_a_date_header_is_bounded(self):
        for header, want in (("600", 120.0), ("soon", 30.0),
                             ("Wed, 07 Oct 2026 07:28:00 GMT", 30.0)):
            with self.subTest(header=header):
                ec._RATE_PAUSE.clear()
                vh.reset()
                t, _ = _hclient([SEARCH_AAPL[:4],
                                 RATES_429 + ({"Retry-After": header},)])
                self._refuse(t)
                self.assertEqual(t.rate_pause_s(), want)
                detail = vh._load(vh._key("etoro", "live"))[
                    "failures"][-1]["detail"]
                self.assertIn(f"Retry-After {header[:40]}", detail)

    def test_the_quota_headers_are_logged(self):
        t, fake = _hclient([SEARCH_AAPL[:4], RATES_429 + (
            {"X-RateLimit-Remaining": "0", "Content-Type": "x"},)])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="INFO") as logs:
            self._refuse(t)
        line = next(m for m in logs.output if "answered 429" in m)
        self.assertIn("X-RateLimit-Remaining", line)
        self.assertNotIn("Content-Type", line)
        self.assertEqual(t.last_rate_headers, {"X-RateLimit-Remaining": "0"})
        # the adapter still reads /rates while its own pause runs
        self.assertGreater(t.rate_pause_s(), 0.0)
        self._refuse(t)
        self.assertEqual(len(_calls(fake, "/rates")), 2)

    def test_a_429_on_the_account_portfolio_or_eligibility_pauses_nothing(self):
        t, _ = _client([("GET", "/aggregate-portfolio", 429, {}),
                        ("GET", "/portfolio", 429, {}),
                        ("POST", "/info/eligibility", 429, {}),
                        SEARCH_AAPL], env="live")
        with self.assertRaises(Exception):
            t.account()
        with self.assertRaises(Exception):
            t.get_positions()
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="WARNING"):
            t.eligibility("AAPL")
        self.assertEqual(t.rate_pause_s(), 0.0)
        self.assertEqual(ec._RATE_PAUSE, {})

    def test_a_5xx_and_a_timeout_pause_nothing(self):
        from tests.test_venue_health import _seq_client
        for step in ((503, {}), requests.ReadTimeout("x")):
            with self.subTest(step=step):
                t, _ = _seq_client({("GET", "/rates"): [step]},
                                   routes=[SEARCH_AAPL], env="live")
                with mock.patch("time.sleep"), self.assertRaises(Exception):
                    t.ticker("AAPL")
                self.assertEqual(t.rate_pause_s(), 0.0)
        self.assertEqual(ec._RATE_PAUSE, {})

    def test_the_pause_ends_by_the_clock(self):
        t, _ = _hclient([SEARCH_AAPL[:4], RATES_429])
        self._refuse(t)
        self.clock.t += 29
        self.assertEqual(t.rate_pause_s(), 1.0)
        self.clock.t += 1
        self.assertEqual(t.rate_pause_s(), 0.0)

    def test_a_429_while_paused_does_not_extend_it(self):
        t, _ = _hclient([SEARCH_AAPL[:4], RATES_429])
        self._refuse(t)
        self.clock.t += 20
        self._refuse(t)
        self.assertEqual(t.rate_pause_s(), 10.0)
        f = vh._load(vh._key("etoro", "live"))["failures"]
        self.assertEqual(len(f), 2, "every 429 that reached the wire is noted")
        self.assertIn("pause running", f[-1]["detail"])

    def test_a_refusal_within_the_streak_is_not_paused_and_one_after_it_is(self):
        t, _ = _hclient([SEARCH_AAPL[:4], RATES_429])
        self._refuse(t)                       # paused until 1030
        self.clock.t = 1030 + 100             # 100 s after its end
        self._refuse(t)
        self.assertEqual(t.rate_pause_s(), 0.0)
        self.assertIn("refused again after its pause",
                      vh._load(vh._key("etoro", "live"))["failures"][-1][
                          "detail"])
        self.clock.t = 1030 + 451             # past the streak
        self._refuse(t)
        self.assertEqual(t.rate_pause_s(), 30.0)

    def test_a_venue_that_keeps_refusing_still_goes_sick(self):
        """One pause, then the next pass's refusals reach the memory. Both
        clocks move: the pause's (_mono) and the memory's (timezone.now)."""
        from datetime import timedelta
        from django.utils import timezone as djtz
        t, _ = _hclient([SEARCH_AAPL[:4], RATES_429])
        wall = [djtz.now()]
        with mock.patch("bot_program.venue_health.timezone.now",
                        lambda: wall[0]), \
                mock.patch("bot_program.notifications.notify_staff") as told:
            self._refuse(t)
            self.assertIsNone(vh.sick("etoro", "live"))
            self.clock.t += 300                # the next pass
            wall[0] += timedelta(seconds=300)
            for _ in range(2):
                self._refuse(t)
            self.assertIsNone(vh.sick("etoro", "live"),
                              "the first pass's note is out of the window")
            self._refuse(t)                    # the third inside 180 s
            self.assertIsNotNone(vh.sick("etoro", "live"))
            self.assertEqual(t.rate_pause_s(), 0.0, "one pause per episode")
        self.assertEqual(told.call_count, 1)

    def test_off_means_no_pause(self):
        with mock.patch.object(ec, "RATE_PAUSE", False):
            t, _ = _hclient([SEARCH_AAPL[:4], RATES_429])
            self._refuse(t)
            self.assertEqual(t.rate_pause_s(), 0.0)
        self.assertEqual(ec._RATE_PAUSE, {})
        self.assertEqual(len(vh._load(vh._key("etoro", "live"))["failures"]),
                         1, "still noted")

    def test_the_adapter_itself_never_refuses_a_read_for_it(self):
        t, fake = _hclient([SEARCH_AAPL[:4], RATES_OK[:4]])
        ec._RATE_PAUSE["live"] = self.clock.t + 30
        self.assertEqual(float(t.ticker("AAPL")["lastPrice"]), 100.0)
        self.assertEqual(len(_calls(fake, "/rates")), 1)
        self.assertEqual(len(_calls(fake, "/market-data/search")), 1)

    def test_a_candle_429_pauses_nothing_and_is_not_noted(self):
        t, fake = _hclient([SEARCH_AAPL[:4], CANDLES_429 + (
            {"X-RateLimit-Remaining": "0"},)])
        with self.assertLogs("bot_program.engine.etoro_client",
                             level="INFO") as logs, \
                self.assertRaises(requests.HTTPError):
            t.klines("AAPL", interval="4h", limit=5)
        self.assertTrue(any("candles answered 429" in m
                            and "X-RateLimit-Remaining" in m
                            for m in logs.output), logs.output)
        self.assertEqual(t.rate_pause_s(), 0.0, "a candle refusal holds "
                                                "no entry")
        self.assertEqual(vh._load(vh._key("etoro", "live")), {},
                         "a candle refusal holds no entry")

    def test_the_writes_never_go_through_the_read(self):
        import inspect
        for name in ("market_order", "close_position", "_patch_position"):
            src = inspect.getsource(getattr(ec.EtoroTrader, name))
            self.assertNotIn("self._read(", src, name)
            self.assertNotIn("rate_pause_s", src, name)


class TheEngineReadsItTests(_PauseOn, SimpleTestCase):

    def test_pause_s_reads_only_a_real_number(self):
        from bot_program.engine.paper_trader import PaperTrader
        from tests.test_venue_min_size import _etoro_like
        ec._RATE_PAUSE["live"] = self.clock.t + 30
        t, _ = _client([], env="live")
        self.assertEqual(vh.pause_s(t), 30.0)
        self.assertEqual(vh.pause_s(_client([], env="demo")[0]), 0.0)
        self.assertEqual(vh.pause_s(mock.MagicMock()), 0.0)
        self.assertEqual(vh.pause_s(_etoro_like()), 0.0)
        bare = type("EtoroTrader", (), {})()
        self.assertEqual(vh.pause_s(bare), 0.0)
        self.assertEqual(vh.pause_s(PaperTrader(None)), 0.0)


# ── the /search "no" ──────────────────────────────────────────────────────

class TheSearchNoTests(_PauseOn, SimpleTestCase):

    def _ask(self, routes, symbol="NOPE", env="live", **kw):
        kw.setdefault("trust_no", True)
        t, fake = _client(routes, env=env)
        with self.assertRaises(LookupError) as cm:
            t.instrument_id(symbol, **kw)
        return cm.exception, len(_calls(fake, "/market-data/search"))

    def test_one_no_is_seen_not_kept(self):
        self._ask([SEARCH_NONE])
        _e, asked = self._ask([SEARCH_NONE])
        self.assertEqual(asked, 1, "one empty 200 blinds nothing")

    def test_two_noes_inside_a_minute_are_one_pass_not_a_confirmation(self):
        self._ask([SEARCH_NONE])
        self.clock.t += 5
        self._ask([SEARCH_NONE])
        self.clock.t += 5
        _e, asked = self._ask([SEARCH_NONE])
        self.assertEqual(asked, 1)

    def test_a_no_confirmed_a_minute_later_is_kept_and_replayed(self):
        first, _ = self._ask([SEARCH_NONE])
        self.clock.t += 61
        self._ask([SEARCH_NONE])
        self.clock.t += 300
        e, asked = self._ask([SEARCH_NONE])
        self.assertEqual(asked, 0, "the kept no answered")
        self.assertIs(type(e), LookupError)
        self.assertTrue(str(e).startswith(str(first)), str(e))
        self.assertIn("eToro's answer twice; not asked again for", str(e))

    def test_the_kept_no_expires(self):
        self._ask([SEARCH_NONE])
        self.clock.t += 61
        self._ask([SEARCH_NONE])
        self.clock.t += ec.SEARCH_NO_TTL_S + 1
        _e, asked = self._ask([SEARCH_NONE])
        self.assertEqual(asked, 1)

    def test_a_refusal_or_an_unmeasured_body_is_never_kept(self):
        for route in (SEARCH_429, ("GET", "/market-data/search", 500, {}),
                      ("GET", "/market-data/search", 200, {"what": 1})):
            with self.subTest(route=route):
                ec._SEARCH_NO.clear()
                for _ in range(2):
                    t, _f = _client([route], env="live")
                    with mock.patch("time.sleep"), \
                            self.assertRaises(Exception):
                        t.instrument_id("NOPE")
                    self.clock.t += 61
                self.assertEqual(ec._SEARCH_NO, {}, route)

    def test_the_lone_result_is_replayed_with_its_names(self):
        lone = ("GET", "/market-data/search", 200,
                [{"instrumentId": 97, "internalSymbolFull": "WHEAT.FUT"}])
        self._ask([lone], symbol="WHEAT")
        self.clock.t += 61
        self._ask([lone], symbol="WHEAT")
        e, asked = self._ask([lone], symbol="WHEAT")
        self.assertEqual(asked, 0)
        self.assertEqual((e.lone_id, e.lone_spelling), (97, "WHEAT.FUT"))

    def test_a_money_read_never_replays_it_and_its_answer_clears_it(self):
        """ticker() (every mark, close price, kill switch, pending close,
        reconcile orphan, TAKE TRADE), eligibility, market_order and
        close_position resolve without trust_no: they ask the wire."""
        import inspect
        self._ask([SEARCH_NONE], symbol="AAPL")
        self.clock.t += 61
        self._ask([SEARCH_NONE], symbol="AAPL")
        self.assertTrue(ec._SEARCH_NO[("live", "AAPL")]["kept"])
        t, fake = _client([SEARCH_AAPL, RATES_OK], env="live")
        self.assertEqual(float(t.ticker("AAPL")["lastPrice"]), 100.0)
        self.assertEqual(len(_calls(fake, "/market-data/search")), 1)
        self.assertNotIn(("live", "AAPL"), ec._SEARCH_NO)
        for name in ("ticker", "_elig_key", "market_order",
                     "close_position"):
            src = inspect.getsource(getattr(ec.EtoroTrader, name))
            self.assertNotIn("trust_no", src, name)
        self.assertIn("self.instrument_id(symbol, trust_no=True)",
                      inspect.getsource(ec.EtoroTrader.klines))

    def test_klines_and_search_no_read_the_kept_no(self):
        self._ask([SEARCH_NONE])
        self.clock.t += 61
        self._ask([SEARCH_NONE])
        t, fake = _client([SEARCH_NONE], env="live")
        with self.assertRaises(LookupError):
            t.klines("NOPE", interval="4h", limit=5)
        self.assertEqual(fake.calls, [])
        self.assertFalse(t._background, "restored after the replay")
        self.assertTrue(t.search_no("NOPE").startswith(
            "eToro knows no instrument spelled 'NOPE'"))
        self.assertEqual(t.search_no("XAGUSD"), "", "a pin has no no")
        self.assertEqual(vh.kept_no(t, "NOPE"), t.search_no("NOPE"))
        self.assertEqual(vh.kept_no(mock.MagicMock(), "NOPE"), "")

    def test_the_worlds_are_kept_apart(self):
        self._ask([SEARCH_NONE])
        self.clock.t += 61
        self._ask([SEARCH_NONE])
        _e, asked = self._ask([SEARCH_NONE], env="demo")
        self.assertEqual(asked, 1)

    def test_off_means_every_call_asks(self):
        with mock.patch.object(ec, "SEARCH_NO_MEMO", False):
            self._ask([SEARCH_NONE])
            self.clock.t += 61
            self._ask([SEARCH_NONE])
            _e, asked = self._ask([SEARCH_NONE])
            self.assertEqual(asked, 1)
            self.assertEqual(self._client_no("NOPE"), "")
        self.assertEqual(ec._SEARCH_NO, {})

    def _client_no(self, symbol):
        return _client([], env="live")[0].search_no(symbol)


# ── the background read: klines for the bar refresh ───────────────────────

class TheBackgroundReadTests(_PauseOn, SimpleTestCase):
    """klines runs inside the adapter's background flag (PR50 M1, M2): its
    /search and its candles go through _read — one retry on a 5xx, the
    wire requests counted, the quota's headers kept — but note nothing on
    the venue's health and grant no 429 pause. The trading lane's own
    reads, before and after, are noted and paused as ever."""

    def setUp(self):
        super().setUp()
        vh.reset()
        self.addCleanup(vh.reset)

    def _memory(self):
        return vh._load(vh._key("etoro", "live"))

    def test_klines_retry_a_5xx_once_and_note_nothing(self):
        t, fake = _sclient({("GET", "/history/candles"):
                            [(500, {}), (200, _candles(3))]},
                           routes=[SEARCH_AAPL[:4]])
        with mock.patch("time.sleep") as slept:
            rows = t.klines("AAPL", interval="4h", limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(_calls(fake, "/history/candles")), 2)
        slept.assert_called_once_with(ec.READ_RETRY_DELAY_S)
        self.assertEqual(self._memory(), {})
        # a candle 5xx twice is the final failure — and still not noted
        t, fake = _sclient({("GET", "/history/candles"): [(503, {})]},
                           routes=[SEARCH_AAPL[:4]])
        with mock.patch("time.sleep"), \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="INFO") as logs, \
                self.assertRaises(requests.HTTPError):
            t.klines("AAPL", interval="4h", limit=3)
        self.assertEqual(len(_calls(fake, "/history/candles")), 2)
        self.assertTrue(any("during a background read — not noted" in m
                            for m in logs.output), logs.output)
        self.assertEqual(self._memory(), {})
        self.assertFalse(t._background)

    def test_the_trading_lane_is_still_noted_after_a_background_raise(self):
        t, _ = _hclient([SEARCH_429])
        with self.assertRaises(requests.HTTPError):
            t.klines("EURUSD", interval="4h", limit=3)
        self.assertFalse(t._background)
        self.assertEqual(self._memory(), {})
        with self.assertRaises(requests.HTTPError):
            t.instrument_id("EURUSD")
        notes = self._memory().get("failures")
        self.assertEqual([(f["where"], f["code"]) for f in notes],
                         [("search", 429)])

    def test_wire_reads_count_every_attempt_and_last_read_names_the_site(self):
        t, fake = _sclient({("GET", "/history/candles"):
                            [(503, {}),
                             (200, _candles(3),
                              {"X-RateLimit-Remaining": "17",
                               "Content-Type": "application/json"})]},
                           routes=[SEARCH_AAPL[:4]])
        self.assertEqual((t.wire_reads, t.last_read, t.last_rate_headers),
                         (0, "", {}))
        with mock.patch("time.sleep"):
            t.klines("AAPL", interval="1h", limit=3)
        self.assertEqual(t.wire_reads, 3, "/search + 2 x /candles")
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(t.last_read, "candles")
        self.assertEqual(t.last_rate_headers, {"X-RateLimit-Remaining": "17"})
        # a warm id costs one more wire request, and no /search
        t.klines("AAPL", interval="1h", limit=3)
        self.assertEqual(t.wire_reads, 4)
        self.assertEqual(len(_calls(fake, "/market-data/search")), 1)

    def test_a_background_search_429_grants_no_rate_pause(self):
        for name, routes in (("/search", [SEARCH_429]),
                             ("/candles", [SEARCH_AAPL[:4], CANDLES_429])):
            with self.subTest(refused=name):
                t, _ = _hclient(routes)
                with self.assertRaises(requests.HTTPError):
                    t.klines("AAPL", interval="4h", limit=3)
                self.assertEqual(t.rate_pause_s(), 0.0)
                self.assertEqual(ec._RATE_PAUSE, {})
                self.assertFalse(t._background)
        self.assertEqual(self._memory(), {})
        # the trading lane's own /search 429 (ticker on a cold symbol)
        # still pauses and is noted once
        t, fake = _hclient([SEARCH_429, RATES_OK[:4]])
        with self.assertRaises(requests.HTTPError):
            t.ticker("AAPL")
        self.assertEqual(t.rate_pause_s(), 30.0)
        self.assertEqual(_calls(fake, "/rates"), [])
        notes = self._memory()["failures"]
        self.assertEqual([(f["where"], f["code"]) for f in notes],
                         [("search", 429)])
        self.assertTrue(notes[0]["detail"].startswith(
            "no Retry-After; paused 30s"), notes[0])
