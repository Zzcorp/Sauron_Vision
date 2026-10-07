"""THE VENUE HEALTH and the order that did not come back (2026-10-05, the
operator asked for more resilience in taking positions).

Three things, one memory:

  1. An eToro order POST whose request never came back is IN DOUBT
     (EtoroOrderInDoubt, in_doubt True): the engine notes the symbol and
     never resends it blind. A connection never made is "not sent" (a
     plain RuntimeError the engine may retry). The in-doubt note clears
     EARLY once the venue reads flat for the symbol twice past its lag.
  2. A READ (rates, search, account, portfolio, eligibility) that answered
     a 5xx or never came back is asked ONCE more; a 429 is not retried; a
     write never is.
  3. Every failure that is the venue's (429, 5xx, transport) is noted on
     ONE memory per (venue, world); three in three minutes — or one order
     failure — make the venue SICK for ten minutes past the last failure.
     execute_entry then holds every NEW real entry (skips.VENUE_SICK);
     closes, stop moves and the TAKE TRADE lane are not held (the ticket
     warns). The staff are told once per episode, with no money figures.

Run with:  python manage.py test tests.test_venue_health
"""
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import venue_health as vh
from bot_program.engine.etoro_client import (EtoroOrderInDoubt, EtoroTrader,
                                             READ_RETRIES, READ_RETRY_DELAY_S)
from tests.test_etoro_client import (ACCEPTED, ELIG_AAPL, SEARCH_AAPL,
                                     _clear_eligibility, _client, _FakeSession,
                                     _Resp)

ORDERS = "/execution/demo/orders"


class _SeqSession(_FakeSession):
    """A fake wire whose answers come in ORDER per (method, url-substring):
    each entry is (status, payload) or an Exception to raise; the last one
    repeats. Everything else falls through to the routes."""

    def __init__(self, seqs, routes=None):
        super().__init__(routes)
        self.seqs = {k: list(v) for k, v in seqs.items()}

    def _hit(self, method, url, **kw):
        for (m, sub), seq in self.seqs.items():
            if m == method and sub in url:
                self.calls.append((method, url, kw))
                step = seq.pop(0) if len(seq) > 1 else seq[0]
                if isinstance(step, Exception):
                    raise step
                return _Resp(*step)
        return super()._hit(method, url, **kw)


def _seq_client(seqs, routes=(), env="demo"):
    t = EtoroTrader("api-k", "user-k", env=env)
    fake = _SeqSession(seqs, routes=list(routes))
    t._session = fake
    return t, fake


def _calls(fake, method, sub):
    return [c for c in fake.calls if c[0] == method and sub in c[1]]


# ── 3. the memory ─────────────────────────────────────────────────────────

class TheMemoryTests(SimpleTestCase):

    def setUp(self):
        vh.reset()
        self.addCleanup(vh.reset)
        self.now = timezone.now()

    def test_the_constants(self):
        self.assertEqual((vh.VENUE_QUIET_MINUTES, vh.SICK_BURST,
                          vh.BURST_WINDOW_S), (10, 3, 180))
        self.assertEqual(vh.WRITE_SITES, frozenset({"order"}))
        self.assertEqual(vh.venue_name("etoro"), "eToro")

    def test_one_read_failure_is_noted_and_makes_nothing_sick(self):
        out = vh.note("etoro", "live", "ticker", code=503, now=self.now)
        self.assertFalse(out["sick"])
        self.assertEqual(len(out["failures"]), 1)
        self.assertIsNone(vh.sick("etoro", "live", now=self.now))

    def test_three_read_failures_inside_the_window_make_the_venue_sick(self):
        with mock.patch("bot_program.notifications.notify_staff") as told:
            vh.note("etoro", "live", "ticker", code=503, now=self.now)
            vh.note("etoro", "live", "search", code=429,
                    now=self.now + timedelta(seconds=30))
            out = vh.note("etoro", "live", "account",
                          detail="ReadTimeout: x",
                          now=self.now + timedelta(seconds=90))
        self.assertTrue(out["sick"])
        s = vh.sick("etoro", "live", now=self.now + timedelta(seconds=91))
        self.assertIsNotNone(s)
        self.assertEqual(s["since"],
                         (self.now + timedelta(seconds=90)).isoformat())
        self.assertEqual(s["until"],
                         (self.now + timedelta(seconds=90, minutes=10))
                         .isoformat())
        self.assertIn("eToro (live) is sick since ", s["words"])
        self.assertIn(" after 3 failures (last: ", s["words"])
        self.assertEqual(s["count"], 3)
        self.assertIn("(last: account ReadTimeout", s["words"])
        self.assertIn("new real entries held until", s["words"])
        self.assertIn("closes and stop moves still go", s["words"])
        # the other world is untouched
        self.assertIsNone(vh.sick("etoro", "demo", now=self.now))
        # told ONCE, at the transition, with no money figures
        self.assertEqual(told.call_count, 1)
        body = told.call_args.kwargs["body"]
        self.assertIn("ticker HTTP 503, search HTTP 429, account ReadTimeout",
                      body)
        self.assertNotIn("$", body)
        self.assertNotIn("USD", body)
        self.assertIn("is sick — new real entries held",
                      told.call_args.kwargs["title"])

    # ── the words (2026-10-07): the real clock, and the episode ─────────

    T0 = datetime(2026, 10, 6, 16, 47, 5, tzinfo=dt_timezone.utc)

    def _three_429s(self):
        with mock.patch("bot_program.notifications.notify_staff") as told:
            for s in (0, 30, 90):
                vh.note("etoro", "live", "ticker", code=429,
                        now=self.T0 + timedelta(seconds=s))
        return told

    def test_the_words_carry_the_real_clock(self):
        told = self._three_429s()
        s = vh.sick("etoro", "live", now=self.T0 + timedelta(seconds=91))
        self.assertEqual(
            s["words"],
            "eToro (live) is sick since 16:48 UTC after 3 failures (last: "
            "ticker HTTP 429 at 16:48 UTC) — new real entries held until "
            "16:58 UTC; closes and stop moves still go")
        body = told.call_args.kwargs["body"]
        self.assertIn("is sick since 16:48 UTC after 3 failures", body)
        self.assertIn("(last: ticker HTTP 429 at 16:48 UTC)", body)
        self.assertIn("held until 16:58 UTC", body)
        self.assertNotIn("?", body)
        self.assertNotIn("USD", body)

    def test_the_words_keep_the_episode_once_the_window_has_passed(self):
        """The operator's 23:42 line read "0 failures in the last 3 min"
        while the hold ran: the window passes long before the quiet."""
        self._three_429s()
        s = vh.sick("etoro", "live",
                    now=self.T0 + timedelta(seconds=90, minutes=5))
        self.assertIn("is sick since 16:48 UTC after 3 failures", s["words"])
        self.assertNotIn("0 failures", s["words"])
        self.assertNotIn("in the last", s["words"])

    def test_a_failure_while_sick_counts_and_moves_the_hold(self):
        self._three_429s()
        later = self.T0 + timedelta(minutes=6)
        vh.note("etoro", "live", "search", code=429, now=later)
        s = vh.sick("etoro", "live", now=later)
        self.assertEqual(s["count"], 4)
        self.assertIn("since 16:48 UTC after 4 failures (last: search HTTP "
                      "429 at 16:53 UTC) — new real entries held until "
                      "17:03 UTC", s["words"])

    def test_a_memory_from_before_the_count_reads_it_off_the_list(self):
        self._three_429s()
        key = vh._key("etoro", "live")
        state = vh._load(key)
        state.pop("sick_failures")
        state.pop("sick_failures_since")
        vh._store(key, state)
        s = vh.sick("etoro", "live", now=self.T0 + timedelta(minutes=4))
        self.assertIn("after 3 failures", s["words"])
        vh.note("etoro", "live", "ticker", code=429,
                now=self.T0 + timedelta(minutes=4))
        self.assertEqual(vh._load(key)["sick_failures"], 4)

    def test_a_count_from_another_episode_is_not_read(self):
        self._three_429s()
        key = vh._key("etoro", "live")
        state = vh._load(key)
        state["sick_failures"] = 40
        state["sick_failures_since"] = "2026-10-05T00:00:00+00:00"
        vh._store(key, state)
        s = vh.sick("etoro", "live", now=self.T0 + timedelta(minutes=4))
        self.assertIn("after 3 failures", s["words"])
        self.assertNotIn("40", s["words"])

    def test_the_refusal_and_the_ticket_carry_the_clock(self):
        self._three_429s()
        at = self.T0 + timedelta(seconds=91)
        live, _ = _client([], env="live")
        code, why = vh.refusal(live, "EURUSD", now=at)
        self.assertTrue(why.startswith("EURUSD: eToro (live) is sick since "
                                       "16:48 UTC"), why)
        self.assertIn("until 16:58 UTC", why)
        self.assertIn("until 16:58 UTC",
                      vh.advisory("etoro", "live", now=at)["reason"])

    def test_the_stamp_never_raises(self):
        self.assertEqual(vh._stamp(None), "?")
        self.assertEqual(vh._stamp("x"), "?")
        self.assertEqual(vh._stamp(self.T0), "16:47 UTC")

    def test_a_429_skip_fits_the_skip_record(self):
        with mock.patch("bot_program.notifications.notify_staff"):
            for i in range(12):
                vh.note("etoro", "live", "eligibility", code=429,
                        detail="no Retry-After; refused again after its "
                               "pause: not paused",
                        now=self.T0 + timedelta(seconds=i))
        _code, why = vh.refusal(_client([], env="live")[0], "NEARUSD",
                                now=self.T0 + timedelta(seconds=12))
        self.assertLessEqual(len(why), 200, why)
        self.assertTrue(why.endswith("— nothing sent"), why)
        self.assertIn("after 12 failures", why)

    def test_recent_refusals_reads_only_429s_inside_the_window(self):
        at = self.T0 + timedelta(seconds=200)
        with mock.patch("bot_program.notifications.notify_staff"):
            for s, code, where in ((0, 429, "ticker"),     # too old
                                   (100, 429, "search"),   # inside
                                   (150, 503, "ticker"),   # not a 429
                                   (190, 429, "ticker")):  # inside
                vh.note("etoro", "live", where, code=code,
                        now=self.T0 + timedelta(seconds=s))
        key = vh._key("etoro", "live")
        state = vh._load(key)
        state["failures"].append({"at": "not a time", "where": "search",
                                  "code": 429, "detail": ""})
        vh._store(key, state)
        got = vh.recent_refusals("etoro", "live", within_s=120, now=at)
        self.assertEqual([(f["where"], f["code"]) for f in got],
                         [("search", 429), ("ticker", 429)],
                         "oldest first; an unreadable time is not recent")
        self.assertEqual(vh.recent_refusals("etoro", "demo", within_s=120,
                                            now=at), [], "worlds apart")
        self.assertEqual(len(vh.recent_refusals("etoro", "live",
                                                within_s=300, now=at)), 3)
        with mock.patch("django.core.cache.cache.get",
                        side_effect=RuntimeError("down")):
            self.assertEqual(vh.recent_refusals("etoro", "live",
                                                within_s=120, now=at), [])

    def test_failures_spread_past_the_window_do_not_count(self):
        for i in range(3):
            out = vh.note("etoro", "live", "ticker", code=503,
                          now=self.now + timedelta(minutes=4 * i))
        self.assertFalse(out["sick"])

    def test_one_order_failure_is_enough_and_the_quiet_extends(self):
        with mock.patch("bot_program.notifications.notify_staff") as told:
            out = vh.note("etoro", "demo", "order",
                          detail="in doubt: ReadTimeout", now=self.now)
            self.assertTrue(out["sick"])
            self.assertEqual(out["until"],
                             (self.now + timedelta(minutes=10)).isoformat())
            # a later failure in the same episode extends the quiet and
            # tells nobody again
            later = self.now + timedelta(minutes=5)
            out2 = vh.note("etoro", "demo", "ticker", code=502, now=later)
            self.assertEqual(out2["until"],
                             (later + timedelta(minutes=10)).isoformat())
            self.assertEqual(out2["since"], self.now.isoformat())
        self.assertEqual(told.call_count, 1)

    def test_the_quiet_expires_by_itself_and_a_new_episode_is_told_again(self):
        with mock.patch("bot_program.notifications.notify_staff") as told:
            vh.note("etoro", "live", "order", code=503, now=self.now)
            gone = self.now + timedelta(minutes=10, seconds=1)
            self.assertIsNone(vh.sick("etoro", "live", now=gone))
            out = vh.note("etoro", "live", "order", code=503, now=gone)
        self.assertTrue(out["sick"])
        self.assertEqual(out["since"], gone.isoformat())
        self.assertEqual(told.call_count, 2)

    def test_the_refusal_is_keyed_on_the_adapter_and_its_world(self):
        from bot_program.asset_engine import skips
        vh.note("etoro", "demo", "order", code=503, now=self.now)
        demo, _ = _client([])
        live, _ = _client([], env="live")
        code, why = vh.refusal(demo, "AAPL", now=self.now)
        self.assertEqual(code, skips.VENUE_SICK)
        self.assertTrue(why.startswith("AAPL: eToro (demo) is sick"), why)
        self.assertTrue(why.endswith("— nothing sent"), why)
        self.assertEqual(vh.refusal(live, "AAPL", now=self.now), ("", ""))
        self.assertEqual(vh.refusal(mock.MagicMock(), "AAPL", now=self.now),
                         ("", ""))
        self.assertEqual(vh.world_of(demo), "demo")
        self.assertEqual(vh.world_of(live), "live")

    def test_the_advisory_warns_and_never_refuses(self):
        self.assertEqual(vh.advisory("etoro", "live", now=self.now),
                         {"ok": True, "reason": ""})
        vh.note("etoro", "live", "order", code=503, now=self.now)
        adv = vh.advisory("etoro", "live", now=self.now)
        self.assertFalse(adv["ok"])
        self.assertIn("eToro (live) is sick", adv["reason"])

    def test_a_cache_that_cannot_answer_calls_nobody_sick(self):
        with mock.patch("django.core.cache.cache.get",
                        side_effect=RuntimeError("redis down")), \
                mock.patch("django.core.cache.cache.set",
                           side_effect=RuntimeError("redis down")):
            out = vh.note("etoro", "live", "order", code=503, now=self.now)
            self.assertFalse(out["sick"])
            self.assertIsNone(vh.sick("etoro", "live", now=self.now))
            self.assertEqual(vh.refusal(_client([])[0], "AAPL"), ("", ""))

    def test_the_skip_code_has_its_words_everywhere(self):
        from bot_program import telegram_eye as eye
        from bot_program.asset_engine import skips
        self.assertEqual(skips.VENUE_SICK, "venue_sick")
        self.assertIn("venue_sick", eye.SKIP_WORDS)
        src = __import__("inspect").getsource(skips.diagnose)
        self.assertIn("VENUE_SICK:", src)


# ── 1 and 2. the adapter ──────────────────────────────────────────────────

class TheOrderThatDidNotComeBackTests(SimpleTestCase):

    def setUp(self):
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _order(self, t, **kw):
        with mock.patch("time.sleep"):
            return t.market_order("AAPL", "BUY", 1.0, stop_loss=180.0,
                                  take_profit=210.0, **kw)

    def test_a_read_timeout_on_the_post_is_in_doubt_never_retried(self):
        t, fake = _seq_client({("POST", ORDERS): [
            requests.ReadTimeout("read timed out")]}, routes=[SEARCH_AAPL])
        coid = str(uuid.uuid4())
        with self.assertRaises(EtoroOrderInDoubt) as cm, \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="ERROR") as logs:
            self._order(t, client_order_id=coid)
        e = cm.exception
        self.assertTrue(getattr(e, "in_doubt", False))
        self.assertIsInstance(e, RuntimeError)
        self.assertEqual(e.reference, coid, "the x-request-id IS the "
                         "caller's UUID, the reference the acceptance echoes")
        self.assertEqual(e.client_order_id, coid)
        self.assertEqual(e.symbol, "AAPL")
        self.assertTrue(str(e).startswith("AAPL: the order request did not "
                                          "come back (ReadTimeout"), str(e))
        self.assertIn("Do not resend it", str(e))
        self.assertIn(coid, str(e))
        self.assertEqual(len(_calls(fake, "POST", ORDERS)), 1,
                         "the POST is never retried")
        self.assertEqual(_calls(fake, "GET", "orders:lookup"), [],
                         "nothing polled: there is no orderId to poll by")
        self.assertTrue(any("IN DOUBT" in m and "NOT retried" in m
                            for m in logs.output))
        # and the venue is sick at once (an ORDER failure)
        s = vh.sick("etoro", "demo")
        self.assertIsNotNone(s)
        self.assertEqual(s["failures"][-1]["where"], "order")
        self.assertIn("in doubt: ReadTimeout", s["failures"][-1]["detail"])

    def test_a_connection_reset_after_the_send_is_in_doubt_too(self):
        t, fake = _seq_client({("POST", ORDERS): [
            requests.ConnectionError("Connection aborted")]},
            routes=[SEARCH_AAPL])
        with self.assertRaises(EtoroOrderInDoubt):
            self._order(t)

    def test_a_connection_never_made_is_not_sent_and_not_in_doubt(self):
        for exc in (requests.ConnectTimeout("connect timed out"),
                    requests.exceptions.SSLError("handshake"),
                    requests.exceptions.ProxyError("refused")):
            with self.subTest(exc=type(exc).__name__):
                vh.reset()
                t, fake = _seq_client({("POST", ORDERS): [exc]},
                                      routes=[SEARCH_AAPL])
                with self.assertRaises(RuntimeError) as cm:
                    self._order(t)
                e = cm.exception
                self.assertFalse(getattr(e, "in_doubt", False))
                self.assertNotIsInstance(e, EtoroOrderInDoubt)
                self.assertIn("eToro unreachable", str(e))
                self.assertIn("was not sent", str(e))
                self.assertEqual(len(_calls(fake, "POST", ORDERS)), 1)
                s = vh.sick("etoro", "demo")
                self.assertIsNotNone(s, "an order that could not be sent "
                                        "is the venue's failure")
                self.assertIn("not sent", s["failures"][-1]["detail"])

    def test_a_5xx_or_429_on_the_post_keeps_its_words_and_sickens_the_venue(self):
        for status in (503, 429):
            with self.subTest(status=status):
                vh.reset()
                t, fake = _client([SEARCH_AAPL,
                                   ("POST", ORDERS, status, {"m": "x"})])
                with self.assertRaises(RuntimeError) as cm:
                    self._order(t)
                self.assertFalse(getattr(cm.exception, "in_doubt", False))
                self.assertIn(f"eToro refused ({status})", str(cm.exception))
                s = vh.sick("etoro", "demo")
                self.assertIsNotNone(s)
                self.assertEqual(s["failures"][-1]["code"], status)

    def test_a_4xx_refusal_is_the_orders_fault_not_the_venues(self):
        t, fake = _client([SEARCH_AAPL, ("POST", ORDERS, 400, {"m": "x"})])
        with self.assertRaises(RuntimeError) as cm:
            self._order(t)
        self.assertIn("eToro refused (400)", str(cm.exception))
        self.assertIsNone(vh.sick("etoro", "demo"))
        self.assertEqual(vh._load(vh._key("etoro", "demo")), {})

    def test_an_accepted_post_is_untouched(self):
        from tests.test_etoro_client import _lookup_router, _measured_lookup
        t, fake = _client([SEARCH_AAPL, ("POST", ORDERS, 200, ACCEPTED)])
        _lookup_router(fake, by_order=(200, _measured_lookup()))
        res = self._order(t)
        self.assertEqual(res["status"], "FILLED")
        self.assertIsNone(vh.sick("etoro", "demo"))


class TheReadRetryTests(SimpleTestCase):

    def setUp(self):
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    RATES = ("GET", "/rates")
    PRICE = (200, {"rates": [{"instrumentId": 1001, "bid": 189.9,
                              "ask": 190.1, "lastExecution": 190.0}]})

    def test_the_constants(self):
        self.assertEqual(READ_RETRIES, 1)
        self.assertEqual(READ_RETRY_DELAY_S, 0.8)

    def test_a_5xx_on_the_rates_read_is_asked_once_more(self):
        t, fake = _seq_client({self.RATES: [(503, {}), self.PRICE]},
                              routes=[SEARCH_AAPL])
        with mock.patch("time.sleep") as sleep:
            tk = t.ticker("AAPL")
        self.assertEqual(float(tk["lastPrice"]), 190.0)
        self.assertEqual(len(_calls(fake, *self.RATES)), 2)
        sleep.assert_called_once_with(READ_RETRY_DELAY_S)
        self.assertEqual(vh._load(vh._key("etoro", "demo")), {},
                         "a retry that answered is not a failure")

    def test_a_read_that_never_came_back_is_asked_once_more(self):
        t, fake = _seq_client(
            {self.RATES: [requests.ReadTimeout("x"), self.PRICE]},
            routes=[SEARCH_AAPL])
        with mock.patch("time.sleep"):
            tk = t.ticker("AAPL")
        self.assertEqual(float(tk["lastPrice"]), 190.0)
        self.assertEqual(len(_calls(fake, *self.RATES)), 2)

    def test_two_failures_are_the_final_answer_and_a_noted_one(self):
        t, fake = _seq_client({self.RATES: [(503, {})]}, routes=[SEARCH_AAPL])
        with mock.patch("time.sleep"), self.assertRaises(RuntimeError):
            t.ticker("AAPL")
        self.assertEqual(len(_calls(fake, *self.RATES)), 1 + READ_RETRIES)
        state = vh._load(vh._key("etoro", "demo"))
        self.assertEqual([f["where"] for f in state["failures"]], ["ticker"])
        self.assertEqual(state["failures"][0]["code"], 503)
        t2, fake2 = _seq_client({self.RATES: [requests.ReadTimeout("x")]},
                                routes=[SEARCH_AAPL])
        with mock.patch("time.sleep"), self.assertRaises(requests.ReadTimeout):
            t2.ticker("AAPL")
        self.assertEqual(len(_calls(fake2, *self.RATES)), 1 + READ_RETRIES)
        state = vh._load(vh._key("etoro", "demo"))
        self.assertEqual(len(state["failures"]), 2)
        self.assertIn("ReadTimeout", state["failures"][-1]["detail"])

    def test_a_429_is_not_retried_but_noted(self):
        t, fake = _seq_client({self.RATES: [(429, {}), self.PRICE]},
                              routes=[SEARCH_AAPL])
        with mock.patch("time.sleep") as sleep, self.assertRaises(RuntimeError):
            t.ticker("AAPL")
        self.assertEqual(len(_calls(fake, *self.RATES)), 1)
        sleep.assert_not_called()
        state = vh._load(vh._key("etoro", "demo"))
        self.assertEqual(state["failures"][-1]["code"], 429)

    def test_the_eligibility_read_retries_a_5xx_and_not_a_429(self):
        sub = ("POST", "/info/demo/eligibility")
        t, fake = _seq_client({sub: [(503, {}), ELIG_AAPL[2:]]},
                              routes=[SEARCH_AAPL])
        with mock.patch("time.sleep"):
            row = t.eligibility("AAPL")
        self.assertIsNotNone(row)
        self.assertEqual(len(_calls(fake, *sub)), 2)
        _clear_eligibility()
        t2, fake2 = _seq_client({sub: [(429, {})]}, routes=[SEARCH_AAPL])
        with mock.patch("time.sleep") as sleep, \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="WARNING"):
            self.assertIsNone(t2.eligibility("AAPL"))
        self.assertEqual(len(_calls(fake2, *sub)), 1)
        sleep.assert_not_called()
        state = vh._load(vh._key("etoro", "demo"))
        self.assertEqual(state["failures"][-1]["where"], "eligibility")

    def test_the_account_portfolio_and_search_reads_retry_too(self):
        t, fake = _seq_client({("GET", "/aggregate-portfolio"): [
            (500, {}), (200, {"accountCurrency": "USD",
                              "accountTotals": {"accountTotalValue": 1.0}})],
            ("GET", "/portfolio"): [(502, {}), (200, {"positions": []})],
            ("GET", "/market-data/search"): [
                requests.ConnectionError("reset"), SEARCH_AAPL[2:]]})
        with mock.patch("time.sleep"):
            self.assertEqual(t.account()["accountCurrency"], "USD")
            self.assertEqual(t.get_positions(), [])
            self.assertEqual(t.instrument_id("AAPL"), 1001)
        self.assertEqual(len(_calls(fake, "GET", "/aggregate-portfolio")), 2)
        self.assertEqual(len(_calls(fake, "GET", "/portfolio")), 2)
        self.assertEqual(len(_calls(fake, "GET", "/market-data/search")), 2)
        self.assertEqual(vh._load(vh._key("etoro", "demo")), {})

    def test_the_lookup_is_not_noted_a_close_answers_500_while_it_works(self):
        t, fake = _client([SEARCH_AAPL, ("GET", "orders:lookup", 500, {})])
        read, code = t._lookup_once({"orderId": "1"})
        self.assertIsNone(read)
        self.assertEqual(code, 500)
        self.assertEqual(vh._load(vh._key("etoro", "demo")), {})

    def test_three_read_failures_in_a_row_sicken_the_venue(self):
        t, fake = _seq_client({self.RATES: [(503, {})]}, routes=[SEARCH_AAPL])
        with mock.patch("time.sleep"):
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    t.ticker("AAPL")
        self.assertIsNotNone(vh.sick("etoro", "demo"))


# ── 3. the engine's gate ──────────────────────────────────────────────────

class TheEntryGateTests(TestCase):
    """execute_entry on a LIVE stock config carried by the REAL EtoroTrader
    over a fake wire (tests.test_etoro_proofs.TheEntryLaneTests' fixture):
    with the demo world sick the entry is HELD with VENUE_SICK, before the
    proof gate (which would say GATE_BLOCKED on this set) and before any
    POST; healthy, the proof gate answers as before."""

    def setUp(self):
        from tests.test_etoro_proofs import _live_cfg, _user, _book
        from tests.test_execution_trust import _instrument, _signal
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        self.user = _user("vh_entry")
        self.cfg = _live_cfg(self.user, name="VH")
        self.cfg.base_currency = "USD"
        self.cfg.save(update_fields=["base_currency"])
        _signal(_instrument(), rule="vh_rule")
        _book(self.user)

    def _cand(self):
        from tests.test_etoro_proofs import ROUTER, _mock_client
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        return cand

    def _execute(self, cand, client):
        from tests.test_etoro_proofs import (PROVEN, ROUTER, SHORTS,
                                             STOCK_UNPROVEN)
        with mock.patch(ROUTER, return_value=client), \
                mock.patch(PROVEN, STOCK_UNPROVEN), \
                mock.patch(SHORTS, frozenset()), \
                mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def test_a_sick_venue_holds_the_entry_before_the_proof_gate(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        t, fake = _client([])
        with mock.patch("bot_program.notifications.notify_staff"):
            vh.note("etoro", "demo", "order", detail="in doubt: ReadTimeout")
        with self.assertLogs("bot_program.asset_engine.base",
                             level="WARNING") as logs:
            res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual(fake.calls, [], "the wire was asked something")
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.VENUE_SICK)
        self.assertTrue(note["detail"].startswith("AAPL: eToro (demo) is sick"),
                        note)
        self.assertIn("nothing sent", note["detail"])
        self.assertTrue(any("HELD" in m for m in logs.output))

    def test_a_healthy_venue_meets_the_proof_gate_as_before(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _client([])
        res = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual(self._skip_note()["code"], skips.GATE_BLOCKED)

    def test_the_gate_sits_before_the_proof_gate_and_a_paper_entry_never_meets_it(self):
        import inspect
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertLess(src.index("venue_health.refusal(client, symbol)"),
                        src.index("self._etoro_entry_refusal("))
        # the refusal reads the ADAPTER: a MagicMock (the desk seam) and a
        # PaperTrader answer ("", "") whatever the memory holds
        from bot_program.engine.paper_trader import PaperTrader
        with mock.patch("bot_program.notifications.notify_staff"):
            vh.note("etoro", "demo", "order", code=503)
        self.assertEqual(vh.refusal(PaperTrader(self.cfg), "AAPL"), ("", ""))
        self.assertEqual(vh.refusal(mock.MagicMock(), "AAPL"), ("", ""))


# ── 1b. the in-doubt note settles early ───────────────────────────────────

class _FlatVenue:
    """A client that declares eToro's lag and answers its position list."""
    PORTFOLIO_LAG_S = 60
    demo = True

    def __init__(self, positions=None, raises=False):
        self.positions = list(positions or [])
        self.raises = raises
        self.asked = 0

    def get_positions(self):
        self.asked += 1
        if self.raises:
            raise requests.ConnectionError("down")
        return list(self.positions)

    def ticker(self, symbol):
        return {"lastPrice": "0"}


class TheInDoubtNoteSettlesTests(TestCase):

    ROUTER = "bot_program.engine.broker_router.client_for_symbol"

    def setUp(self):
        from tests.test_order_lifecycle import _bot
        self.user = User.objects.create_user("vh_doubt", password="x")
        self.bot, self.cfg = _bot(self.user)
        self.bot._remember_in_doubt("AAPL", "REF-1")
        self.cfg.refresh_from_db()

    def _age(self, seconds, **more):
        extras = dict(self.cfg.extras or {})
        note = dict(extras["entry_in_doubt"]["AAPL"])
        note["at"] = (timezone.now() - timedelta(seconds=seconds)).isoformat()
        note.update(more)
        extras["entry_in_doubt"]["AAPL"] = note
        self.cfg.extras = extras
        self.cfg.save(update_fields=["extras"])
        self.bot.cfg.refresh_from_db()
        return self.bot._in_doubt_note("AAPL")

    def _note(self):
        self.cfg.refresh_from_db()
        return (self.cfg.extras.get("entry_in_doubt") or {}).get("AAPL")

    def test_the_constant(self):
        self.assertEqual(self.bot.IN_DOUBT_FLAT_READS, 2)

    def test_a_note_younger_than_the_lag_is_not_even_read(self):
        venue = _FlatVenue()
        note = self._age(30)
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(self.bot._settle_in_doubt("AAPL", note))
        self.assertEqual(venue.asked, 0)
        self.assertIsNotNone(self._note())

    def test_two_flat_reads_a_lag_apart_clear_the_note(self):
        from bot_program.asset_engine import skips
        venue = _FlatVenue()
        note = self._age(61)
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(self.bot._settle_in_doubt("AAPL", note))
        self.assertEqual(venue.asked, 1)
        n = self._note()
        self.assertEqual(n["flat_reads"], 1)
        self.assertIn("flat_read_at", n)
        # the second read inside the lag of the first proves nothing
        self.bot._tick_broker_cache = {}
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(self.bot._settle_in_doubt("AAPL", self._note()))
        self.assertEqual(venue.asked, 1)
        # a lag later: flat again — cleared, and propose_entry no longer
        # refuses the symbol for the note
        self.bot._tick_broker_cache = {}
        n = self._age(130, flat_reads=1, flat_read_at=(
            timezone.now() - timedelta(seconds=61)).isoformat())
        with mock.patch(self.ROUTER, return_value=venue), \
                self.assertLogs("bot_program.asset_engine.base",
                                level="INFO") as logs:
            self.assertTrue(self.bot._settle_in_doubt("AAPL", n))
        self.assertIsNone(self._note())
        self.assertTrue(any("left no position" in m for m in logs.output))
        self.bot._remember_in_doubt("AAPL", "REF-2")
        self._age(130, flat_reads=1, flat_read_at=(
            timezone.now() - timedelta(seconds=61)).isoformat())
        self.bot._tick_broker_cache = {}
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertIsNone(self.bot.propose_entry("AAPL"))
        self.cfg.refresh_from_db()
        last = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertNotEqual(last["code"], skips.ORDER_IN_DOUBT, last)
        self.assertIsNone(self._note())

    def test_a_venue_that_holds_the_symbol_keeps_the_note_and_adopts_nothing(self):
        from bot_program.models import AssetBotTrade
        for rows in ([{"symbol": "AAPL", "qty": 1.0, "side": "BUY",
                       "position_id": "9"}],
                     [{"symbol": "", "qty": 1.0, "side": "BUY",
                       "position_id": "9", "symbol_unresolved": True}]):
            with self.subTest(rows=rows):
                venue = _FlatVenue(rows)
                note = self._age(61)
                self.bot._tick_broker_cache = {}
                with mock.patch(self.ROUTER, return_value=venue), \
                        self.assertLogs("bot_program.asset_engine.base",
                                        level="WARNING") as logs:
                    self.assertFalse(self.bot._settle_in_doubt("AAPL", note))
                self.assertTrue(any("nothing is adopted" in m
                                    for m in logs.output))
                self.assertIsNotNone(self._note())
                self.assertNotIn("flat_reads", self._note())
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_a_venue_that_cannot_be_asked_or_declares_no_lag_keeps_the_note(self):
        note = self._age(61)
        with mock.patch(self.ROUTER, return_value=_FlatVenue(raises=True)):
            self.assertFalse(self.bot._settle_in_doubt("AAPL", note))
        self.assertNotIn("flat_reads", self._note())
        self.bot._tick_broker_cache = {}
        with mock.patch(self.ROUTER, return_value=mock.MagicMock()):
            self.assertFalse(self.bot._settle_in_doubt("AAPL", note))
        self.assertNotIn("flat_reads", self._note())
        # and propose_entry still refuses the symbol on the note
        from bot_program.asset_engine import skips
        with mock.patch(self.ROUTER, return_value=mock.MagicMock()):
            self.assertIsNone(self.bot.propose_entry("AAPL"))
        self.cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(self.cfg)["AAPL"]["code"],
                         skips.ORDER_IN_DOUBT)


# ── the manual lane warns ─────────────────────────────────────────────────

class TheManualLaneWarnsTests(TestCase):

    def setUp(self):
        vh.reset()
        self.addCleanup(vh.reset)
        self.user = User.objects.create_user("vh_manual", password="x")

    def test_the_advisory_reads_the_users_world_and_only_warns(self):
        from tests.test_etoro_routing import _etoro
        from bot_program.manual_trade import venue_health_advisory
        _etoro(self.user, demo=False)
        self.assertEqual(venue_health_advisory(self.user, "etoro"),
                         {"ok": True, "reason": ""})
        with mock.patch("bot_program.notifications.notify_staff"):
            vh.note("etoro", "live", "order", code=503)
        adv = venue_health_advisory(self.user, "etoro")
        self.assertFalse(adv["ok"])
        self.assertIn("eToro (live) is sick", adv["reason"])
        # a paper ticket, another carrier, the other world: ok
        self.assertTrue(venue_health_advisory(self.user, "etoro",
                                              live=False)["ok"])
        self.assertTrue(venue_health_advisory(self.user, "ibkr")["ok"])
        self.user.etoro_account.demo = True
        self.user.etoro_account.save(update_fields=["demo"])
        self.assertTrue(venue_health_advisory(self.user, "etoro")["ok"])

    def test_a_user_with_no_etoro_row_is_never_warned(self):
        from bot_program.manual_trade import venue_health_advisory
        self.assertTrue(venue_health_advisory(self.user, "etoro")["ok"])

    def test_the_preview_carries_it_and_the_popup_renders_it_without_blocking(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        manual = (base / "bot_program" / "manual_trade.py").read_text(
            encoding="utf-8")
        self.assertIn('"venue_health": venue_health_advisory(user, '
                      'ticket_stamp["carrier"],', manual)
        html = (base / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("p.venue_health", html)
        self.assertIn("THE VENUE IS SICK", html)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("vhealth", expr)
        self.assertNotIn("venue_health", expr)
