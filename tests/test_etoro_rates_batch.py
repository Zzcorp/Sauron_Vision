"""FEWER eTORO READS (2026-11-01, bot_program/engine/etoro_rates.py): one
batched rates call per pass, the clock gate first, one read per half hour
through a weekend shut, a shared cache the marks take at 30 s.

  * EtoroTrader.tickers(symbols): ONE GET, instrumentIds a comma list, in
    chunks of at most twenty, through the budget at the caller's priority.
    Every row is matched to its symbol by the row's OWN instrumentId, never
    by its position; a row missing for a symbol raises for that symbol
    alone (its reader takes the single read, and no later batch of the
    pass carries it again); a zero row is the "0" sentinel; a priced row
    is the price. An answer it does not trust (no instrumentId, more rows
    than asked, an id not asked, no row at all for two or more ids, a
    shape it does not know) is logged once with its keys, never a price,
    and the batch is unproven for a day: every symbol is read alone
    meanwhile.
  * The fleet pass prefetches ONE batched snapshot of the open real rows
    whose stop rests at eToro; their marks read it. A failed batch is ONE
    failure toward SICK, not one per row. A live row eToro holds no stop
    for is marked alone on the wire every tick, as before.
  * A cached mark never acts alone: a stop move (the mirror's retry of an
    unchanged lock included), a care close or a change of the care's
    state decided on a mark read off the cache is decided again on ONE
    fresh read of the wire first, judged by the mark sanity as the row's
    own read was.
  * The proposals past the clock gate share one batched read, and a live
    proposal judges the clock BEFORE its rates read: a shut market costs
    no rates read for an entry. A proposal priced off the cache or a
    batch is never ordered on that price alone: its last look fails
    closed.
  * The shut-market cadence: through a weekend or a holiday shut of a
    forex or commodity market whose clock is known (the venue's own week
    for forex), a live mark is read off the newest answer received since
    the shut began while it is younger than half an hour, so one read
    per half hour serves every row of it; full cadence from ten minutes
    before the reopen; crypto never shuts, and stocks and ETFs keep full
    cadence (eToro trades US share CFDs out of session); a nightly or
    daily break, a missing, unknown or failing clock is full cadence.
  * The shared cache, keyed (world, instrument id), kept half an hour:
    every answer writes it; the marks and the care read it at 30 s or
    less (a shut market's at the cadence's half hour), the proposals past
    the clock gate at 30 s or less, the TAKE TRADE preview at 10 s or
    less; the last look, the order, the pending-close mark and the orphan
    mark never. A cached mark's age rides wherever it is booked or shown.
  * Every money path still refuses a 0.

The suite runs with the cache and the cadence OFF (tests/__init__.py);
these tests turn them on.

Run with:  python manage.py test tests.test_etoro_rates_batch
"""
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils.dateparse import parse_datetime

from bot_program import entry_timing as et
from bot_program import venue_health as vh
from bot_program.engine import etoro_budget as eb
from bot_program.engine import etoro_client as ec
from bot_program.engine import etoro_rates as er
from tests.test_etoro_client import _Resp, _clear_eligibility

USER_KEY = "user-k"
KH = eb.key_hash(USER_KEY)
ROUTER = "bot_program.engine.broker_router.client_for_symbol"
UTC = dt_tz.utc
#: a Saturday: the NYSE is shut until Monday 13:30 UTC
#: (tests.test_paper_market_hours.SAT)
SAT = datetime(2026, 9, 26, 13, 53, 54, tzinfo=UTC)
#: the Monday after, before the NYSE's 13:30 UTC open
MON = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
#: the Sunday between: CME Globex reopens at 22:00 UTC (17:00 Chicago)
SUN = datetime(2026, 9, 27, 21, 30, tzinfo=UTC)
#: the Friday before: 17:00 New York, the FX week's close, is 21:00 UTC
FRI_CLOSE = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)
#: a Tuesday inside CME Globex's daily break (21:00 to 22:00 UTC)
TUE_BREAK = datetime(2026, 9, 29, 21, 15, tzinfo=UTC)
#: a Tuesday night: the NYSE is shut until 13:30 UTC
TUE_NIGHT = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
#: a winter Friday at 16:30 New York: eToro's FX week runs to 22:00 UTC,
#: while the FOREX row's UTC hours shut at 21:00 UTC
FRI_WINTER = datetime(2026, 11, 6, 21, 30, tzinfo=UTC)
#: the platform symbols of these tests and the ids eToro answers them by
IDS = {"AAA": 11, "BBB": 22, "CCC": 33, "DDD": 44, "EEE": 55}


def _row(iid, last, *, key="instrumentId"):
    """One rate row as eToro is BELIEVED to answer a batch: its own id
    beside bid/ask/lastExecution (unmeasured; manage.py etoro_rates_shape
    measures it). A zero `last` is a row with nothing in it."""
    if not last:
        return {key: iid, "bid": 0, "ask": 0, "lastExecution": 0}
    return {key: iid, "bid": round(last - 0.1, 4), "ask": round(last + 0.1, 4),
            "lastExecution": last}


class _NotJson(_Resp):
    def json(self):
        raise ValueError("Expecting value: line 1 column 1")


class _Wire:
    """A fake eToro wire. /rates answers every asked id from `prices` (id
    -> last, or None for no row), one row each carrying its own id;
    `body`, a callable of the asked ids, answers instead when given;
    `alone_only` ids are answered only to a read of one id (a batch leaves
    them out); `status` may be a list, consumed in order, the last one
    repeating. Every other request answers (200, {}), as
    tests.test_etoro_client._FakeSession does."""

    def __init__(self, prices=None, *, body=None, status=200, alone_only=(),
                 not_json=False):
        self.prices = dict(prices or {})
        self.body = body
        self.status = (list(status) if isinstance(status, (list, tuple))
                       else [status])
        self.alone_only = set(alone_only)
        self.not_json = not_json
        self.calls = []
        self.headers = {}

    def _rates(self, ids):
        status = self.status.pop(0) if len(self.status) > 1 else self.status[0]
        if self.not_json:
            return _NotJson(status, {})
        if self.body is not None:
            return _Resp(status, self.body(ids))
        rows = [_row(i, self.prices[i]) for i in ids
                if i in self.prices and self.prices[i] is not None
                and not (len(ids) > 1 and i in self.alone_only)]
        return _Resp(status, {"rates": rows})

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if "/instruments/rates" in url:
            raw = str((kw.get("params") or {}).get("instrumentIds") or "")
            return self._rates([int(x) for x in raw.split(",") if x])
        return _Resp(200, {})

    def _write(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return _Resp(200, {})

    def post(self, url, **kw):
        return self._write("POST", url, **kw)

    def patch(self, url, **kw):
        return self._write("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._write("DELETE", url, **kw)

    def rates(self) -> list:
        """The instrumentIds of every rates GET, in order."""
        return [c[2]["params"]["instrumentIds"] for c in self.calls
                if "/instruments/rates" in c[1]]

    def sets(self) -> list:
        """rates(), each request's ids sorted: the manage walk goes newest
        row first (AssetBotTrade's ordering), which is not these tests'
        point."""
        return [",".join(str(i) for i in sorted(int(x) for x in s.split(",")))
                for s in self.rates()]


def _trader(wire, *, env="live", ids=None):
    """The real adapter over `wire`, its ids already resolved (no /search)."""
    t = ec.EtoroTrader("api-k", USER_KEY, env=env)
    t._session = wire
    for s, i in (IDS if ids is None else ids).items():
        t._ids[s] = i
        t._symbols[i] = s
        t._venue_spelling[i] = s
    return t


class _Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


class _RatesOn:
    """The shared rates cache ON over a clean cache, its wall clock
    (`clock`, the real now to start) and the failure memo's (`mono`)
    moved by the test; the budget and the cadence OFF, as in the suite."""

    def setUp(self):
        super().setUp()
        cache.clear()
        er.reset()
        p = mock.patch.object(er, "CACHE", True)
        p.start()
        self.addCleanup(p.stop)
        self.clock = _Clock(time.time())
        p = mock.patch.object(er, "_now", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.mono = _Clock(10_000.0)
        p = mock.patch.object(er, "_mono", self.mono)
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        self.addCleanup(er.reset)
        self.addCleanup(cache.clear)

    @contextmanager
    def _at(self, when):
        """The wall clock at `when` for Django and for the rates cache."""
        self.clock.t = when.timestamp()
        with mock.patch("django.utils.timezone.now", return_value=when):
            yield

    def _later(self, seconds):
        return datetime.fromtimestamp(self.clock.t + seconds, tz=UTC)


class _ShutOn(_RatesOn):
    """And the shut-market cadence ON — with the paper clock's gate ON, as
    in production: with it off (the suite's default) mark_sanity reads
    every market open, and a shut market's repeated answer would read as
    a frozen feed after FROZEN_MINUTES."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(er, "SHUT_CADENCE", True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("bot_program.engine.paper_trader.MARKET_HOURS_GATE",
                       True)
        p.start()
        self.addCleanup(p.stop)


def _user(name):
    return User.objects.create_user(username=name, password="x")


def _etoro_account(user, *, demo=False):
    """eToro carries every class for `user` (broker_router reads these
    flags; the router itself is patched)."""
    from bot_program.models import EtoroAccount
    return EtoroAccount.objects.create(
        user=user, demo=demo, is_primary_for_stocks=True,
        is_primary_for_forex=True, is_primary_for_commodity=True,
        is_primary_for_crypto=True)


def _cfg(user, name, symbols=(), asset_class="stock"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="live",
        symbols=list(symbols), capital=Decimal("10000"), enabled=True)


def _held(cfg, symbol, *, protected=True, **kw):
    """A real long of 10 at 100, stop 98, target 104 (tests.test_exit_truth).
    Its stop and target rest at eToro (a P3 mark) unless `protected` is
    False: eToro then holds no stop for it (a P1 mark)."""
    from tests.test_exit_truth import _trade
    return _trade(cfg, symbol=symbol, metadata={
        "initial_stop_loss": 98.0, "protected": protected, "broker": "etoro",
        "broker_env": "live", "broker_position_id": f"p-{symbol}"}, **kw)


def _instrument(symbol, asset_class, exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange, "is_active": True})
    return inst


def _tick(cfg, t):
    """One manage tick of `cfg` with every eToro client the router builds
    answered by `t`."""
    from bot_program.asset_engine.base import make_bot
    with mock.patch(ROUTER, return_value=t), \
            mock.patch("bot_program.notifications.notify_staff"):
        return make_bot(cfg).manage_positions()


def _note(cfg, symbol):
    from bot_program.asset_engine import skips
    cfg.refresh_from_db()
    return skips.last_by_symbol(cfg).get(symbol) or {}


# ── the parser's shapes ──────────────────────────────────────────────────

class TheParserTests(_RatesOn, SimpleTestCase):

    def _answer(self, symbols, **wire):
        w = _Wire(**wire)
        t = _trader(w)
        return t.tickers(symbols), w

    def test_one_get_carries_the_ids_as_one_comma_list(self):
        got, w = self._answer(["AAA", "BBB"], prices={11: 10.0, 22: 20.0})
        self.assertEqual(w.rates(), ["11,22"])
        self.assertEqual(got["AAA"], {"lastPrice": "10.0", "symbol": "AAA",
                                      "bid": "9.9", "ask": "10.1"})
        self.assertEqual(got["BBB"]["lastPrice"], "20.0")
        self.assertIn("/api/v1/market-data/instruments/rates", w.calls[0][1])

    def test_rows_are_matched_by_their_own_id_never_by_their_position(self):
        got, _ = self._answer(
            ["AAA", "BBB", "CCC"],
            body=lambda ids: {"rates": [_row(33, 30.0), _row(11, 10.0),
                                        _row(22, 20.0)]})
        self.assertEqual({s: got[s]["lastPrice"] for s in got},
                         {"AAA": "10.0", "BBB": "20.0", "CCC": "30.0"})
        self.assertIsNone(er.unproven(), "a reordered answer is trusted")

    def test_the_id_spelled_instrumentID_is_the_rows_own_id_too(self):
        got, _ = self._answer(
            ["AAA", "BBB"],
            body=lambda ids: {"rates": [_row(22, 20.0, key="instrumentID"),
                                        _row(11, 10.0, key="instrumentID")]})
        self.assertEqual((got["AAA"]["lastPrice"], got["BBB"]["lastPrice"]),
                         ("10.0", "20.0"))

    def test_a_missing_row_raises_for_that_symbol_alone(self):
        got, _ = self._answer(["AAA", "BBB"], prices={11: 10.0, 22: None})
        self.assertEqual(got["AAA"]["lastPrice"], "10.0")
        self.assertIsInstance(got["BBB"], er.RowMissing)
        self.assertIn("no row for BBB (id 22)", str(got["BBB"]))
        self.assertFalse(er.final(got["BBB"]), "its reader reads it alone")
        self.assertIsNone(er.unproven(), "a missing row is no distrust")

    def test_a_zero_row_is_the_zero_sentinel_and_a_priced_row_the_price(self):
        got, _ = self._answer(
            ["AAA", "BBB"],
            body=lambda ids: {"rates": [
                {"instrumentId": 11, "bid": 0, "ask": None,
                 "lastExecution": 0},
                {"instrumentId": 22, "bid": 19.9, "ask": 20.1}]})
        self.assertEqual(got["AAA"], {"lastPrice": "0", "symbol": "AAA"})
        self.assertEqual(got["BBB"], {"lastPrice": "20.0", "symbol": "BBB",
                                      "bid": "19.9", "ask": "20.1"})

    # an answer it does not trust: one test per shape

    def _untrusted(self, why, **wire):
        with self.assertLogs("bot_program.engine.etoro_rates",
                             level="WARNING") as logs:
            got, w = self._answer(["AAA", "BBB"], **wire)
        for s in ("AAA", "BBB"):
            self.assertIsInstance(got[s], er.BatchUnproven, s)
            self.assertFalse(er.final(got[s]), "each is read alone")
        held = er.unproven()
        self.assertIsNotNone(held)
        self.assertIn(why, held["why"])
        self.assertEqual(len(logs.records), 1, "logged once")
        return logs.output[0], w

    def test_rows_with_no_instrument_id_are_untrusted(self):
        line, _ = self._untrusted(
            "a row with no instrumentId of its own",
            body=lambda ids: {"rates": [
                {"bid": 123.4501, "ask": 123.4599, "lastExecution": 123.455},
                {"bid": 7.0101, "ask": 7.0199, "lastExecution": 7.015}]})
        # the keys, never a price
        self.assertIn("'bid'", line)
        self.assertIn("'lastExecution'", line)
        for price in ("123.45", "7.01"):
            self.assertNotIn(price, line)

    def test_more_rows_than_asked_are_untrusted(self):
        self._untrusted("3 rows for 2 ids asked",
                        body=lambda ids: {"rates": [_row(11, 1.0),
                                                    _row(22, 2.0),
                                                    _row(33, 3.0)]})

    def test_an_id_that_was_not_asked_is_untrusted(self):
        self._untrusted("an id that was not asked",
                        body=lambda ids: {"rates": [_row(11, 1.0),
                                                    _row(99, 2.0)]})

    def test_the_same_id_twice_is_untrusted(self):
        self._untrusted("the same id twice",
                        body=lambda ids: {"rates": [_row(11, 1.0),
                                                    _row(11, 1.5)]})

    def test_a_shape_the_parser_does_not_know_is_untrusted(self):
        self._untrusted("a shape the parser does not know",
                        body=lambda ids: {"data": [_row(11, 1.0)]})

    def test_a_list_body_is_untrusted(self):
        self._untrusted("a shape the parser does not know",
                        body=lambda ids: [_row(11, 1.0), _row(22, 2.0)])

    def test_rates_that_are_not_a_list_are_untrusted(self):
        self._untrusted("a shape the parser does not know",
                        body=lambda ids: {"rates": {"11": _row(11, 1.0)}})

    def test_a_row_with_no_rate_key_is_untrusted(self):
        self._untrusted("a row with none of bid/ask/lastExecution",
                        body=lambda ids: {"rates": [
                            {"instrumentId": 11, "price": 1.0},
                            _row(22, 2.0)]})

    def test_a_rate_that_is_not_a_number_is_untrusted(self):
        self._untrusted("a rate that is not a number",
                        body=lambda ids: {"rates": [
                            {"instrumentId": 11, "bid": "n/a", "ask": 1.0},
                            _row(22, 2.0)]})

    def test_a_body_that_is_not_json_is_untrusted(self):
        self._untrusted("a body that is not JSON", not_json=True)

    def test_a_4xx_to_the_comma_list_is_untrusted(self):
        self._untrusted("HTTP 400 to a batched read", status=400,
                        prices={11: 1.0, 22: 2.0})

    def test_no_row_at_all_for_two_ids_is_untrusted(self):
        """An empty list, the answer ticker() reads as "no rate" for ONE
        id, is no answer to a comma list: trusted, every symbol would be
        missing and read alone on every pass, the batch never turning off
        (2026-11-01, review)."""
        self._untrusted("no row came back for any of the 2 ids asked",
                        body=lambda ids: {"rates": []})
        er.reset()
        self._untrusted("no row came back for any of the 2 ids asked",
                        body=lambda ids: {"rates": None})

    def test_rows_of_zeros_for_every_id_are_trusted(self):
        """A shut market's answer: a row for each id, each priced 0. Rows
        came back, each with its own id: the "0" sentinels, no distrust."""
        got, _ = self._answer(["AAA", "BBB"], prices={11: 0, 22: 0})
        self.assertEqual(got["AAA"], {"lastPrice": "0", "symbol": "AAA"})
        self.assertEqual(got["BBB"], {"lastPrice": "0", "symbol": "BBB"})
        self.assertIsNone(er.unproven())

    def test_one_id_with_no_row_is_missing_not_distrust(self):
        got, _ = self._answer(["AAA"], body=lambda ids: {"rates": []})
        self.assertIsInstance(got["AAA"], er.RowMissing)
        self.assertIsNone(er.unproven(), "one id's empty list is ticker()'s")

    def test_an_unproven_batch_sends_nothing_for_a_day_then_asks_again(self):
        self._untrusted("a row with no instrumentId of its own",
                        body=lambda ids: {"rates": [{"bid": 1.0, "ask": 1.1},
                                                    {"bid": 2.0, "ask": 2.1}]})
        w = _Wire(prices={11: 10.0, 22: 20.0})
        t = _trader(w)
        self.clock.t += 23 * 3600
        got = t.tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), [], "nothing sent while unproven")
        self.assertIsInstance(got["AAA"], er.BatchUnproven)
        self.clock.t += 3600 + 1
        er._UNPROVEN_HERE.clear()      # another process: the shared mark only
        cache.delete(er.UNPROVEN_KEY)  # LocMem keeps no TTL of a moved clock
        got = t.tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), ["11,22"], "asked again after the day")
        self.assertEqual(got["AAA"]["lastPrice"], "10.0")

    def test_the_unproven_mark_lives_a_day_on_the_cache_clock(self):
        er.mark_unproven("a row with no instrumentId of its own", "keys")
        self.assertIsNotNone(er.unproven())
        self.assertIsNotNone(er.unproven(now=self.clock.t + 24 * 3600 - 1))
        er._UNPROVEN_HERE.clear()
        self.assertIsNone(er.unproven(now=self.clock.t + 24 * 3600 + 1))

    def test_chunks_of_at_most_twenty_ids(self):
        ids = {f"S{i:02d}": 100 + i for i in range(25)}
        w = _Wire(prices={i: 1.0 + n for n, i in enumerate(ids.values())})
        t = _trader(w, ids=ids)
        got = t.tickers(list(ids))
        self.assertEqual([len(x.split(",")) for x in w.rates()], [20, 5])
        self.assertEqual(len([g for g in got.values() if isinstance(g, dict)]),
                         25)

    def test_every_answer_single_or_batch_writes_the_shared_cache(self):
        w = _Wire(prices={11: 10.0, 22: 0, 33: 30.0})
        t = _trader(w)
        t.tickers(["AAA", "BBB"])
        t.ticker("CCC")
        a = er.get("live", 11, symbol="AAA", max_age_s=30)
        self.assertEqual((a["lastPrice"], a["bid"], a["ask"], a["cached"]),
                         ("10.0", "9.9", "10.1", True))
        self.assertEqual(er.get("live", 22, symbol="BBB", max_age_s=30)
                         ["lastPrice"], "0", "a zero answer stays a zero")
        self.assertEqual(er.get("live", 33, symbol="CCC", max_age_s=30)
                         ["lastPrice"], "30.0")
        self.assertIsNone(er.get("demo", 11, symbol="AAA", max_age_s=30),
                          "keyed by world")

    def test_a_budget_refusal_sends_nothing_and_is_no_failure(self):
        from tests.test_etoro_budget import _fill
        eb.reset()
        self.addCleanup(eb.reset)
        p = mock.patch.object(eb, "BUDGET", True)
        p.start()
        self.addCleanup(p.stop)
        _fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3))
        w = _Wire(prices={11: 10.0, 22: 20.0})
        t = _trader(w)
        with eb.at(eb.P3, "mark"):
            got = t.tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), [])
        self.assertTrue(getattr(got["AAA"], "budget_refused", False))
        self.assertTrue(er.final(got["AAA"]))
        self.assertEqual(vh._load(vh._key("etoro", "live")), {})

    def test_the_batch_is_taken_once_at_the_callers_priority(self):
        seen = []
        real = eb.take
        eb.reset()
        self.addCleanup(eb.reset)
        p = mock.patch.object(eb, "BUDGET", True)
        p.start()
        self.addCleanup(p.stop)

        def take(kh, family, priority, **kw):
            seen.append((family, priority, kw.get("where")))
            return real(kh, family, priority, **kw)
        w = _Wire(prices={11: 10.0, 22: 20.0, 33: 30.0})
        t = _trader(w)
        with mock.patch.object(eb, "take", take), eb.at(eb.P4, "proposal"):
            t.tickers(["AAA", "BBB", "CCC"])
        self.assertEqual(seen, [("market", eb.P4, "rates")],
                         "one token for three ids")

    def test_a_failed_batch_is_one_request_and_one_note_per_instrument(
            self):
        # 2026-11-02 (completes E2, review): one note per instrument the
        # failed GET carried, as the reads alone it replaced were noted
        # (it was ..._and_one_health_note: ONE note, so a failing venue
        # took three failed batches to make SICK where three rows read
        # alone made it, and a new real entry SICK would hold could go)
        w = _Wire(prices={11: 10.0, 22: 20.0}, status=503)
        t = _trader(w)
        with mock.patch("time.sleep"):
            got = t.tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), ["11,22", "11,22"], "its one retry")
        for s in ("AAA", "BBB"):
            self.assertIsInstance(got[s], er.BatchFailed)
            self.assertTrue(er.final(got[s]))
        failures = vh._load(vh._key("etoro", "live"))["failures"]
        self.assertEqual(len(failures), 2)
        self.assertEqual({f["code"] for f in failures}, {503})
        self.assertIn("noted once per instrument", str(got["AAA"]))

    def test_a_429_batch_grants_the_shared_pause_once(self):
        p = mock.patch.object(ec, "RATE_PAUSE", True)
        p.start()
        self.addCleanup(p.stop)
        eb.reset()
        self.addCleanup(eb.reset)
        w = _Wire(prices={11: 10.0, 22: 20.0}, status=429)
        t = _trader(w)
        got = t.tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), ["11,22"], "a 429 is never retried")
        self.assertIsInstance(got["AAA"], er.BatchFailed)
        self.assertGreater(t.rate_pause_s(), 0, "the batch is a pause site")
        # one pause, and one note per instrument (2026-11-02: one note)
        self.assertEqual(len(vh._load(vh._key("etoro", "live"))["failures"]),
                         2)
        self.assertEqual(len(eb._PAUSE_KEYS), 1)

    def test_a_cold_id_is_never_batched(self):
        """A batch carries only ids named without the wire: a /search costs
        its own request, as before."""
        w = _Wire(prices={11: 10.0, 22: 20.0})
        t = _trader(w, ids={"AAA": 11})
        self.assertEqual(er._wanted(t, ["AAA", "ZZZ"], fresh_s=15), ["AAA"])


# ── the fallback ─────────────────────────────────────────────────────────

class TheFallbackTests(_RatesOn, TestCase):

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(_user("rb_fallback"), "F")
        self.rows = [_held(self.cfg, s) for s in ("AAA", "BBB")]

    def test_a_symbol_missing_from_the_batch_takes_the_single_read(self):
        w = _Wire(prices={11: 101.0, 22: 102.0}, alone_only={22})
        _tick(self.cfg, _trader(w))
        self.assertEqual(w.sets(), ["11,22", "22"])
        for row, price in zip(self.rows, (101.0, 102.0)):
            row.refresh_from_db()
            self.assertEqual(row.metadata["venue_mark"]["price"], price)

    def test_an_unproven_batch_reads_every_symbol_alone(self):
        w = _Wire(body=lambda ids: {"rates": [
            {"bid": 100.9, "ask": 101.1, "lastExecution": 101.0}
            for _ in ids]})
        with self.assertLogs("bot_program.engine.etoro_rates",
                             level="WARNING"):
            _tick(self.cfg, _trader(w))
        self.assertEqual(w.sets()[0], "11,22")
        self.assertEqual(sorted(w.sets()[1:]), ["11", "22"], "each alone")
        self.clock.t += 300
        self.mono.t += 300
        _tick(self.cfg, _trader(w))
        self.assertEqual(sorted(w.rates()[3:]), ["11", "22"],
                         "no batch for a day")


def _empty_to_lists(prices):
    """A wire that answers {"rates": []} to any comma list and the row to
    a single id: the batch shape eToro may answer a list it cannot bind
    (unmeasured; manage.py etoro_rates_shape measures it)."""
    def body(ids):
        if len(ids) > 1:
            return {"rates": []}
        return {"rates": [_row(i, prices[i]) for i in ids if i in prices]}
    return _Wire(body=body)


class TheEmptyBatchTests(_RatesOn, TestCase):
    """AN EMPTY ANSWER TURNS THE BATCH OFF, AND A MISSING ROW IS NOT ASKED
    IN BATCH AGAIN (2026-11-01, review): trusted, an answer with no row
    cost every pass a batch and then each row's single read — and each
    later row of the walk a batch of the rows the last one left out."""

    def setUp(self):
        super().setUp()
        self.user = _user("rb_empty")
        _etoro_account(self.user)
        self.cfg = _cfg(self.user, "E")

    def _pass(self, t):
        from bot_program.asset_engine import runner
        with mock.patch(ROUTER, return_value=t), \
                mock.patch("bot_program.notifications.notify_staff"), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           ".can_open_new", return_value=(False, "test")):
            return runner.run_all_asset_bots()

    def test_an_empty_answer_costs_one_batch_then_the_single_reads(self):
        rows = [_held(self.cfg, s) for s in ("AAA", "BBB", "CCC")]
        w = _empty_to_lists({11: 101.0, 22: 102.0, 33: 103.0})
        with self.assertLogs("bot_program.engine.etoro_rates",
                             level="WARNING"):
            self._pass(_trader(w))
        self.assertEqual(w.sets()[0], "11,22,33")
        self.assertEqual(sorted(w.sets()[1:]), ["11", "22", "33"],
                         "the batch once, then each row alone, no re-batch")
        self.assertIsNotNone(er.unproven(), "the batch is off")
        for row, price in zip(rows, (101.0, 102.0, 103.0)):
            row.refresh_from_db()
            self.assertEqual(row.metadata["venue_mark"]["price"], price)
        self.clock.t += 300
        self.mono.t += 300
        self._pass(_trader(w))
        self.assertEqual(sorted(w.sets()[4:]), ["11", "22", "33"],
                         "no batch while unproven: as before the batch")

    def test_rows_a_batch_left_out_are_read_alone_and_never_rebatched(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        _held(self.cfg, "CCC")
        _held(self.cfg, "DDD")
        w = _Wire(prices={11: 101.0, 22: 102.0, 33: 103.0, 44: 104.0},
                  alone_only={22, 44})
        self._pass(_trader(w))
        self.assertEqual(w.sets()[0], "11,22,33,44")
        self.assertEqual(sorted(w.sets()[1:]), ["22", "44"],
                         "the two left out, each alone, never batched again")
        self.assertIsNone(er.unproven(), "a missing row is no distrust")


# ── one GET for N rows in a pass ─────────────────────────────────────────

class TheFleetPassTests(_RatesOn, TestCase):

    def setUp(self):
        super().setUp()
        self.user = _user("rb_fleet")
        _etoro_account(self.user)
        self.a = _cfg(self.user, "A")
        self.b = _cfg(self.user, "B")

    def _pass(self, t):
        from bot_program.asset_engine import runner
        with mock.patch(ROUTER, return_value=t), \
                mock.patch("bot_program.notifications.notify_staff"), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           ".can_open_new", return_value=(False, "test")):
            return runner.run_all_asset_bots()

    def test_one_get_for_n_rows_across_configs(self):
        rows = ([_held(self.a, s) for s in ("AAA", "BBB", "CCC")]
                + [_held(self.b, s) for s in ("DDD", "EEE")])
        prices = (101.0, 102.0, 103.0, 101.5, 102.5)
        w = _Wire(prices=dict(zip((11, 22, 33, 44, 55), prices)))
        self._pass(_trader(w))
        self.assertEqual(w.sets(), ["11,22,33,44,55"],
                         "one batched read for five rows, none alone")
        for row, price in zip(rows, prices):
            row.refresh_from_db()
            self.assertEqual(row.metadata["venue_mark"]["price"], price)

    def test_a_row_etoro_holds_no_stop_for_is_marked_alone_every_tick(self):
        _held(self.a, "AAA")
        bare = _held(self.a, "BBB", protected=False)
        w = _Wire(prices={11: 101.0, 22: 102.0})
        self._pass(_trader(w))
        self.assertEqual(w.rates(), ["11", "22"],
                         "the bare row's mark is its own read on the wire")
        bare.refresh_from_db()
        self.assertEqual(bare.metadata["venue_mark"]["price"], 102.0)

    def test_a_working_entry_is_never_in_the_snapshot(self):
        from tests.test_exit_truth import _trade
        _held(self.a, "AAA")
        _trade(self.a, symbol="BBB", broker_order_id="77", metadata={
            "initial_stop_loss": 98.0, "entry_working": True,
            "protected": True, "broker": "etoro"})
        w = _Wire(prices={11: 101.0, 22: 102.0})
        with mock.patch("bot_program.asset_engine.base.AssetBot"
                        "._poll_working_entry"):
            self._pass(_trader(w))
        self.assertEqual(w.rates(), ["11"])


# ── one SICK failure per failed batch ────────────────────────────────────

class TheOneFailureTests(_RatesOn, TestCase):

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(_user("rb_sick"), "S")
        self.rows = [_held(self.cfg, s) for s in ("AAA", "BBB", "CCC")]

    def test_a_failed_batch_counts_each_row_toward_sick_as_its_read_did(
            self):
        # 2026-11-02 (completes E2, review): was ..._is_one_failure_toward_
        # sick_not_one_per_row (one note, never SICK). The money rule:
        # entries are never sent more often, and three rows that fail
        # alone make eToro sick (the control below), so the one request
        # that carried them notes the three failures it stands for
        w = _Wire(prices={11: 101.0, 22: 102.0, 33: 103.0}, status=503)
        with mock.patch("time.sleep"):
            _tick(self.cfg, _trader(w))
        self.assertEqual(w.sets(), ["11,22,33", "11,22,33"],
                         "one batch and its one retry, no read per row")
        state = vh._load(vh._key("etoro", "live"))
        self.assertEqual(len(state["failures"]), 3)
        self.assertIsNotNone(vh.sick("etoro", "live"))
        for s in ("AAA", "BBB", "CCC"):
            self.assertTrue(_note(self.cfg, s)["detail"].startswith(
                "open position only clock-managed: the mark could not be "
                "read (BatchFailed: the batched rates read failed (HTTP "
                "503)"), s)
        for row in self.rows:
            row.refresh_from_db()
            self.assertEqual(row.status, "OPEN")

    def test_the_same_three_rows_read_alone_were_three(self):
        """The control: the switch off, each row asks for itself and each
        failure is noted — three inside 180 s make eToro sick."""
        w = _Wire(prices={11: 101.0, 22: 102.0, 33: 103.0}, status=503)
        with mock.patch.object(er, "CACHE", False), mock.patch("time.sleep"):
            _tick(self.cfg, _trader(w))
        self.assertEqual(sorted(w.rates()),
                         ["11", "11", "22", "22", "33", "33"])
        self.assertEqual(
            len(vh._load(vh._key("etoro", "live"))["failures"]), 3)
        self.assertIsNotNone(vh.sick("etoro", "live"))

    def test_the_next_pass_asks_again(self):
        w = _Wire(prices={11: 101.0, 22: 102.0, 33: 103.0},
                  status=[503, 503, 200])
        with mock.patch("time.sleep"):
            _tick(self.cfg, _trader(w))
        self.clock.t += 300
        self.mono.t += 300
        _tick(self.cfg, _trader(w))
        self.assertEqual(w.sets()[2:], ["11,22,33"])
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].metadata["venue_mark"]["price"], 101.0)


class TheRefusalMemoTests(_RatesOn, SimpleTestCase):
    """A batch the budget refused is kept for its symbols as a failed one
    is — but only for readers at its priority or below: a proposal's
    refusal (P4, the stricter floor) never closes a mark (P3)."""

    def setUp(self):
        super().setUp()
        from tests.test_etoro_budget import _fill
        eb.reset()
        self.addCleanup(eb.reset)
        p = mock.patch.object(eb, "BUDGET", True)
        p.start()
        self.addCleanup(p.stop)
        self.fill = _fill
        self.w = _Wire(prices={11: 101.0, 22: 102.0})
        self.t = _trader(self.w)

    def test_a_proposals_refusal_never_closes_a_mark(self):
        self.fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P4))
        with eb.at(eb.P4, "proposal"):
            got = er.prefetch(self.t, ["AAA", "BBB"])
        self.assertTrue(getattr(got["AAA"], "budget_refused", False))
        self.assertEqual(self.w.rates(), [])
        with eb.at(eb.P3, "mark"):
            tick = er.quote(self.t, "AAA", max_age_s=30, refill=["BBB"])
        self.assertEqual(tick["lastPrice"], "101.0")
        self.assertEqual(self.w.sets(), ["11,22"], "the mark asked its own")

    def test_a_marks_refusal_closes_a_proposal(self):
        self.fill(KH, eb.MARKET, eb.limit(eb.MARKET, eb.P3))
        with eb.at(eb.P3, "mark"):
            er.prefetch(self.t, ["AAA", "BBB"])
        with eb.at(eb.P4, "proposal"), self.assertRaises(eb.Refused):
            er.quote(self.t, "AAA", max_age_s=30, refill=["BBB"])
        self.assertEqual(self.w.rates(), [])

    def test_a_failed_batch_closes_every_reader(self):
        w = _Wire(prices={11: 101.0, 22: 102.0}, status=503)
        t = _trader(w)
        with eb.at(eb.P4, "proposal"), mock.patch("time.sleep"):
            er.prefetch(t, ["AAA", "BBB"])
        with eb.at(eb.P3, "mark"), self.assertRaises(er.BatchFailed):
            er.quote(t, "AAA", max_age_s=30, refill=["BBB"])
        self.assertEqual(w.sets(), ["11,22", "11,22"], "nothing more asked")


# ── P0 and P1: no cache round trip on their path ─────────────────────────

class TheOffPathTests(_ShutOn, SimpleTestCase):
    """THE BUDGET'S RULE (engine/etoro_budget, the spend queue): not one
    cache round trip stands between a close and the wire, a close and its
    proofs, two closes of the kill switch or the drain, or an order and
    its last look. A rates answer read at P0 or P1 (the kill switch's and
    the drain's marks, the CLOSE button's, the last look, a bare row's
    mark, any read no caller classified) still writes the shared cache and
    the cadence's memo, OFF its path: this process's writer thread writes
    it, and every reader of the cache drains this process's queue first."""

    def _recorder(self, events, **kw):
        from tests.test_etoro_budget import _Recorder
        return _Recorder(events, **kw)

    def test_a_p0_or_p1_answer_is_written_off_its_path(self):
        for scope in (eb.P0, eb.P1, None):
            with self.subTest(scope=scope):
                cache.clear()
                er.reset()
                events = []
                t = _trader(_Wire(prices={11: 101.0}))
                with mock.patch.object(er, "_cache",
                                       return_value=self._recorder(events)):
                    if scope is None:
                        tick = t.ticker("AAA")       # unclassified: P1
                    else:
                        with eb.at(scope, "close"):
                            tick = t.ticker("AAA")
                    on_the_path = list(events)
                self.assertEqual(tick["lastPrice"], "101.0")
                self.assertEqual(on_the_path, [], "no cache call on its path")
                er.flush_writes()
                self.assertEqual(er.get("live", 11, symbol="AAA",
                                        max_age_s=30)["lastPrice"], "101.0")
                # the shut-market cadence's memory is the answer itself,
                # kept its half hour (2026-11-01, review: no memo of its own)
                self.assertIsNotNone(er.get("live", 11, symbol="AAA",
                                            max_age_s=er.SHUT_EVERY_S))

    def test_a_stalled_cache_holds_no_close_mark(self):
        gate, events = threading.Event(), []
        stalled = self._recorder(events, gate=gate, stall_s=1.0)
        t = _trader(_Wire(prices={11: 101.0, 22: 102.0}))
        with mock.patch.object(er, "_cache", return_value=stalled):
            started = time.monotonic()
            with eb.at(eb.P0, "kill switch"):
                t.ticker("AAA")
                t.ticker("BBB")
            took = time.monotonic() - started
            gate.set()                           # the cache answers again
            er.flush_writes()
        self.assertLess(took, 0.75, f"the marks waited {took:.2f}s on the "
                                    f"rates cache")
        self.assertEqual(er.get("live", 22, symbol="BBB", max_age_s=30)
                         ["lastPrice"], "102.0")

    def test_a_mark_at_p3_writes_on_its_own_path(self):
        events = []
        t = _trader(_Wire(prices={11: 101.0}))
        with mock.patch.object(er, "_cache",
                               return_value=self._recorder(events)):
            with eb.at(eb.P3, "mark"):
                t.ticker("AAA")
        self.assertIn("cache set_many", events)

    def test_a_reader_is_answered_by_what_this_process_queued(self):
        t = _trader(_Wire(prices={11: 101.0}))
        with mock.patch.object(er, "_wake_writer"):  # no writer thread runs
            with eb.at(eb.P0, "kill switch"):
                t.ticker("AAA")
            # the rate: the cadence keeps no memo of its own since
            # 2026-11-01 (review), the answer is its memory
            self.assertEqual(len(er._WRITES), 1)
            with eb.at(eb.P3, "mark"):
                got = er.get("live", 11, symbol="AAA", max_age_s=30)
        self.assertEqual(got["lastPrice"], "101.0")
        self.assertEqual(len(er._WRITES), 0)

    def test_the_writer_writes_with_no_reader(self):
        t = _trader(_Wire(prices={11: 101.0}))
        with eb.at(eb.P0, "kill switch"):
            t.ticker("AAA")
        deadline = time.monotonic() + 5.0
        while (cache.get(er._key("live", 11)) is None
               and time.monotonic() < deadline):
            time.sleep(0.01)
        self.assertIsNotNone(cache.get(er._key("live", 11)))

    def test_a_forked_child_writes_its_own_and_never_waits_on_its_parent(
            self):
        parents, theirs = er._WRITES_LOCK, er._WRITES
        parents.acquire()             # a drain the parent was in at the fork
        try:
            theirs.append((er._put_many_now,
                           ("live", {99: {"lastPrice": "1"}}, er._now())))
            er._after_fork_in_child()
            self.assertIsNot(er._WRITES, theirs)
            self.assertEqual(len(er._WRITES), 0, "the parent's are its own")
            t = _trader(_Wire(prices={11: 101.0}))
            with eb.at(eb.P0, "kill switch"):
                t.ticker("AAA")
            er.flush_writes()         # never waits on the parent's lock
        finally:
            theirs.clear()
            parents.release()
        self.assertIsNotNone(cache.get(er._key("live", 11)))
        self.assertIsNone(cache.get(er._key("live", 99)))


# ── the clock gate before the proposal's read; one snapshot ──────────────

def _buy():
    from bot_program.asset_engine.base import BotDecision
    return BotDecision(direction="BUY", score=0.9, reasons=["t"],
                       rule_name="rb_rule")


class TheClockFirstTests(TestCase):
    """Unconditional: the cache's switch does not move the gate."""

    def _propose_at(self, cfg, t, when):
        from bot_program.asset_engine.stock_bot import StockBot
        with mock.patch.object(et, "GATE", True), \
                mock.patch("django.utils.timezone.now", return_value=when), \
                mock.patch(ROUTER, return_value=t), \
                mock.patch("bot_program.asset_engine.stock_bot.StockBot"
                           ".decide", return_value=_buy()):
            return StockBot(cfg).propose_entry("AAA")

    def test_a_shut_market_costs_one_rates_read_a_shut_for_an_entry(self):
        # 2026-11-02 (completes E2, review): was ..._costs_no_rates_read_
        # for_an_entry. The clock first skipped the entry quote's memory
        # too (below): ONE read of each shut feeds it, and every later
        # refusal of that shut asks nothing, where every tick of it asked
        # before the clock went first
        from bot_program.asset_engine import skips
        cfg = _cfg(_user("rb_clock"), "K", symbols=["AAA"])
        w = _Wire(prices={11: 101.0})
        t = _trader(w)
        for later in (0, 5 * 60, 20 * 3600):
            self.assertIsNone(self._propose_at(
                cfg, t, SAT + timedelta(seconds=later)))
        self.assertEqual(w.rates(), ["11"], "one read for the whole shut")
        note = _note(cfg, "AAA")
        self.assertEqual(note["code"], skips.MARKET_SHUT)
        self.assertTrue(note["detail"].startswith(
            "the stock market is shut until Monday 13:30 UTC — new entries "
            "resume 13:45 UTC"), note)
        cfg.refresh_from_db()
        self.assertEqual(cfg.extras["entry_marks"]["AAA"]["mid"], 101.0)

    def test_a_feed_frozen_through_the_shut_is_held_at_the_reopen(self):
        """2026-11-02 (completes E2, review): the clock-first move skipped
        _entry_quote_gate on a shut market, and with it the memory the
        freeze rule reads (extras["entry_marks"]): a feed still showing
        the shut's price after the reopen was a first sighting there, where
        every refused tick of the shut had recorded that price, and the
        freeze rule (FROZEN_MINUTES in an open market) let entries go on it
        until 45 minutes after the reopen. The shut's one read is the
        memory now, so the frozen feed is held at once, as before."""
        from bot_program.asset_engine import skips
        cfg = _cfg(_user("rb_clock_frozen"), "K", symbols=["AAA"])
        w = _Wire(prices={11: 101.0})
        t = _trader(w)
        self.assertIsNone(self._propose_at(cfg, t, SAT))
        monday = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
        self.assertIsNone(self._propose_at(cfg, t, monday))
        note = _note(cfg, "AAA")
        self.assertEqual(note["code"], skips.SUSPECT_MARK, note)
        self.assertIn("frozen quote: 101 unchanged for", note["detail"])

    def test_a_feed_that_moved_at_the_reopen_is_not_held(self):
        # the control: the shut's price was read, the reopen's moved
        from bot_program.asset_engine import skips
        cfg = _cfg(_user("rb_clock_moved"), "K", symbols=["AAA"])
        w = _Wire(prices={11: 101.0})
        t = _trader(w)
        self.assertIsNone(self._propose_at(cfg, t, SAT))
        w.prices[11] = 101.4
        monday = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
        self._propose_at(cfg, t, monday)
        self.assertNotEqual(_note(cfg, "AAA").get("code"),
                            skips.SUSPECT_MARK)

    def test_an_open_clock_reads_the_rate(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(_user("rb_clock_open"), "K", symbols=["AAA"])
        w = _Wire(prices={11: 101.0})
        with mock.patch.object(et, "GATE", True), \
                mock.patch("bot_program.entry_timing.verdict",
                           return_value={"ok": True, "code": "", "why": "",
                                         "until": None, "attack": None}), \
                mock.patch(ROUTER, return_value=_trader(w)), \
                mock.patch("bot_program.asset_engine.stock_bot.StockBot"
                           ".decide", return_value=_buy()):
            StockBot(cfg).propose_entry("AAA")
        self.assertEqual(w.rates(), ["11"])


class TheProposalReadsTheWireTests(_RatesOn, TestCase):
    """2026-11-02 (completes E2, review): an order is never priced from a
    cache or a batch snapshot, and a proposal's quote IS the order's
    price — its stop, its target and its size are built on it, and the
    last look can only refuse. So each proposal reads its own rate on the
    wire, as before the batch; the snapshot serves the marks alone. (These
    tests were TheProposalSnapshotTests: one batched read for the config's
    proposals past the clock, and a proposal priced off the cache with its
    age on the row.)"""

    def setUp(self):
        super().setUp()
        self.user = _user("rb_prop")
        _etoro_account(self.user)

    def _propose(self, cfg, t):
        from bot_program.asset_engine import runner
        candidates = []
        with mock.patch(ROUTER, return_value=t), \
                mock.patch("bot_program.asset_engine.stock_bot.StockBot"
                           ".decide", return_value=_buy()), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           ".can_open_new", return_value=(True, "")):
            runner._propose_phase(cfg, signal_stats={},
                                  candidates=candidates,
                                  not_desked={"paper": [], "live": []},
                                  summaries=[])
        return candidates

    def test_each_proposal_reads_its_own_rate_on_the_wire(self):
        cfg = _cfg(self.user, "P", symbols=["AAA", "BBB", "CCC"])
        w = _Wire(prices={11: 101.0, 22: 102.0, 33: 103.0})
        cands = self._propose(cfg, _trader(w))
        self.assertEqual(w.rates(), ["11", "22", "33"])
        self.assertEqual(sorted(c.symbol for c in cands),
                         ["AAA", "BBB", "CCC"])
        by = {c.symbol: c for c in cands}
        self.assertEqual(by["BBB"].market_price, 102.0)

    def test_a_symbol_the_clock_refuses_asks_no_rate(self):
        cfg = _cfg(self.user, "P", symbols=["AAA", "BBB", "CCC"])
        w = _Wire(prices={11: 101.0, 22: 102.0, 33: 103.0})
        shut = {"ok": False, "code": "SHUT", "why": "shut", "until": None,
                "attack": None}
        open_ = {"ok": True, "code": "", "why": "", "until": None,
                 "attack": None}
        with mock.patch.object(et, "GATE", True), \
                mock.patch("bot_program.entry_timing.verdict",
                           side_effect=lambda s, *a, **k: (
                               shut if s == "BBB" else open_)):
            self._propose(cfg, _trader(w))
        self.assertEqual(w.rates(), ["11", "33"])

    def test_a_cached_answer_never_prices_a_proposal(self):
        cfg = _cfg(self.user, "P", symbols=["AAA", "BBB"])
        w = _Wire(prices={11: 101.0, 22: 102.0})
        t = _trader(w)
        t.tickers(["AAA", "BBB"])           # a fresh answer in the cache
        w.prices.update({11: 101.5, 22: 102.5})
        self.clock.t += 12
        cands = self._propose(cfg, t)
        self.assertEqual(w.rates(), ["11,22", "11", "22"],
                         "each proposal read the wire")
        by = {c.symbol: c for c in cands}
        self.assertEqual((by["AAA"].market_price, by["BBB"].market_price),
                         (101.5, 102.5), "priced on the wire's answer")
        for c in cands:
            self.assertNotIn("proposal_quote_age_s", c.level_meta)
            self.assertNotIn("proposal_quote_batched", c.level_meta)


# ── the shut-market cadence ──────────────────────────────────────────────

class TheShutCadenceTests(_ShutOn, TestCase):
    """The clock decides whether a live mark may be read off an answer up
    to half an hour old. The rows here are a commodity (COMEX: CME
    Globex's clock, shut from Friday 21:00 to Sunday 22:00 UTC) unless a
    test names another: stocks and ETFs keep full cadence."""

    def setUp(self):
        super().setUp()
        self.cfg = _cfg(_user("rb_shut"), "W")

    def _ticks(self, row_symbol, start, minutes, *, venue=("commodity",
                                                          "COMEX"), **row):
        if venue:
            _instrument(row_symbol, *venue)
        row = _held(self.cfg, row_symbol, **row)
        w = _Wire(prices={11: 101.0, 22: 102.0})
        t = _trader(w)
        for m in minutes:
            with self._at(start + timedelta(minutes=m)):
                _tick(self.cfg, t)
        return w, row

    def test_a_shut_market_row_is_read_once_per_half_hour(self):
        w, row = self._ticks("AAA", SAT, [0, 5])
        self.assertEqual(w.rates(), ["11"], "not asked again in the half hour")
        # MARKED off the half hour's answer, not left clock-managed: the
        # row is managed on the shut market's price and records no skip
        # (2026-11-01, review)
        self.assertEqual(_note(self.cfg, "AAA"), {})
        self.assertEqual(vh._load(vh._key("etoro", "live")), {},
                         "never a failure")
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertEqual(parse_datetime(row.metadata["venue_mark"]["at"]),
                         SAT, "the stamp is dated at the read")
        with self._at(SAT + timedelta(minutes=31)):
            _tick(self.cfg, _trader(w))
        self.assertEqual(w.rates(), ["11", "11"], "read again after 30 min")
        row.refresh_from_db()
        self.assertEqual(parse_datetime(row.metadata["venue_mark"]["at"]),
                         SAT + timedelta(minutes=31))

    def test_crypto_is_never_shut(self):
        w, _ = self._ticks("AAA", SAT, [0, 5, 10], venue=("crypto",),
                           asset_class="crypto")
        self.assertEqual(w.rates(), ["11", "11", "11"])

    def test_full_cadence_from_ten_minutes_before_the_reopen(self):
        # Sunday 21:35 read, 21:45 off it (15 min before 22:00), 21:51 read
        w, _ = self._ticks("AAA", SUN, [5, 15, 21])
        self.assertEqual(w.rates(), ["11", "11"])

    def test_an_unknown_reopen_means_full_cadence(self):
        clock = {"is_open": False, "session": "CME", "modelled": True,
                 "reopens": None, "reopens_words": "", "opened": None,
                 "closed": SAT - timedelta(hours=17)}
        with mock.patch("core.exchange_status.market_clock",
                        return_value=clock):
            w, _ = self._ticks("AAA", SAT, [0, 5])
        self.assertEqual(w.rates(), ["11", "11"])

    def test_an_unknown_start_of_the_shut_means_full_cadence(self):
        clock = {"is_open": False, "session": "CME", "modelled": True,
                 "reopens": SAT + timedelta(hours=32), "reopens_words": "",
                 "opened": None, "closed": None}
        with mock.patch("core.exchange_status.market_clock",
                        return_value=clock):
            w, _ = self._ticks("AAA", SAT, [0, 5])
        self.assertEqual(w.rates(), ["11", "11"])

    def test_a_failing_clock_means_full_cadence(self):
        with mock.patch("core.exchange_status.market_clock",
                        side_effect=RuntimeError("no calendar")):
            w, _ = self._ticks("AAA", SAT, [0, 5])
        self.assertEqual(w.rates(), ["11", "11"])

    def test_an_unmodelled_class_means_full_cadence(self):
        w, _ = self._ticks("AAA", SAT, [0, 5], venue=("cfd",))
        self.assertEqual(w.rates(), ["11", "11"])

    def test_an_index_cfd_keeps_full_cadence(self):
        """Its clock is the cash session's; eToro's CFD trades through the
        night (entry_timing.SHUT_CLASSES leaves the index out too)."""
        w, _ = self._ticks("AAA", SAT, [0, 5], venue=("index",))
        self.assertEqual(w.rates(), ["11", "11"])

    def test_a_row_etoro_holds_no_stop_for_keeps_full_cadence(self):
        w, _ = self._ticks("AAA", SAT, [0, 5], protected=False)
        self.assertEqual(w.rates(), ["11", "11"])

    def test_the_fleet_pass_asks_nothing_for_a_held_row(self):
        from bot_program.asset_engine import runner
        _etoro_account(self.cfg.user)
        _instrument("AAA", "commodity", "COMEX")
        _instrument("BBB", "commodity", "COMEX")
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        w = _Wire(prices={11: 101.0, 22: 102.0})
        t = _trader(w)
        for m in (0, 5):
            with self._at(SAT + timedelta(minutes=m)), \
                    mock.patch(ROUTER, return_value=t), \
                    mock.patch("bot_program.notifications.notify_staff"), \
                    mock.patch("bot_program.asset_engine.base.AssetBot"
                               ".can_open_new", return_value=(False, "t")):
                runner.run_all_asset_bots()
        self.assertEqual(w.rates(), ["11,22"])

    # ── where the exchange's clock is not eToro's (2026-11-01, review) ──

    def test_a_stock_keeps_full_cadence_through_a_weekend(self):
        """eToro filled a US share CFD 22 minutes before the NYSE open
        (bot_program/entry_timing) and trades many through the night:
        the NYSE's clock is not the venue's, so no stock is slowed."""
        w, _ = self._ticks("AAA", SAT, [0, 5], venue=("stock", "NYSE"))
        self.assertEqual(w.rates(), ["11", "11"])

    def test_an_etf_keeps_full_cadence_on_a_weekday_night(self):
        w, _ = self._ticks("AAA", TUE_NIGHT, [0, 5], venue=("etf", "NYSE"))
        self.assertEqual(w.rates(), ["11", "11"])

    def test_a_winter_friday_keeps_forex_at_full_cadence_to_the_venues_close(
            self):
        """From November to March the FOREX row's UTC hours shut at 21:00
        UTC, an hour before eToro's 17:00 New York week: that hour is the
        venue's, and the care's weekend lock runs in it."""
        w, row = self._ticks("AAA", FRI_WINTER, [0, 5, 35, 40],
                             venue=("forex", ""))
        # 21:30 and 21:35 read (16:30, 16:35 New York); 22:05 read: the
        # 21:35 answer predates the venue's close; 22:10 off the 22:05 one
        self.assertEqual(w.rates(), ["11", "11", "11"])

    def test_the_weekend_lock_of_a_winter_friday_reaches_the_venue(self):
        """The money in that hour: a forex long at 100, stop 98 (R = 2),
        at +0.6R at the 21:03 UTC tick only. The care's weekend lock
        (break-even + 0.1R) goes to eToro on that tick, as it did before
        the cadence: every tick of the hour reads the wire."""
        from tests.test_aragorn import _switch
        _switch("aragorn")
        _instrument("AAA", "forex", "")
        row = _held(self.cfg, "AAA", asset_class="forex")
        row.metadata = dict(row.metadata, protective_trade_id="p-AAA")
        row.save()
        w = _Wire(prices={11: 100.8})
        t = _trader(w)
        start = datetime(2026, 11, 6, 20, 58, tzinfo=UTC)
        for m in range(0, 60, 5):                 # 20:58 to 21:53 UTC
            w.prices[11] = 101.2 if m == 5 else 100.8
            with self._at(start + timedelta(minutes=m)):
                _tick(self.cfg, t)
        self.assertEqual(len(w.rates()), 12, "a read every tick")
        self.assertEqual(_patches(w), [Decimal("100.2")])
        row.refresh_from_db()
        self.assertEqual(row.stop_loss, Decimal("100.2"))

    def test_an_unknown_commodity_venue_means_full_cadence(self):
        """An exchange no table names reads CME by default: a clock stated,
        never known. The legacy sync writes 'ETORO'; /setup/ writes ''."""
        for n, exchange in enumerate(("ETORO", "")):
            with self.subTest(exchange=exchange):
                symbol = ("AAA", "BBB")[n]
                cfg = _cfg(self.cfg.user, f"U{n}")
                _instrument(symbol, "commodity", exchange)
                _held(cfg, symbol)
                w = _Wire(prices={11: 101.0, 22: 102.0})
                t = _trader(w)
                for m in (0, 5):
                    with self._at(SAT + timedelta(minutes=m)):
                        _tick(cfg, t)
                self.assertEqual(len(w.rates()), 2, w.rates())

    def test_a_row_with_no_instrument_row_means_full_cadence(self):
        """Its class is the config's, its venue unknown."""
        cfg = _cfg(self.cfg.user, "C", asset_class="commodity")
        _held(cfg, "AAA")
        w = _Wire(prices={11: 101.0})
        t = _trader(w)
        for m in (0, 5):
            with self._at(SAT + timedelta(minutes=m)):
                _tick(cfg, t)
        self.assertEqual(w.rates(), ["11", "11"])

    def test_a_daily_break_keeps_full_cadence(self):
        """CME Globex's hour between 21:00 and 22:00 UTC: a shut shorter
        than a day is a break eToro's own hours may not keep."""
        w, _ = self._ticks("AAA", TUE_BREAK, [0, 5])
        self.assertEqual(w.rates(), ["11", "11"])

    def test_an_answer_from_before_the_shut_is_no_shut_markets_mark(self):
        """Read at 20:58 UTC, two minutes before the FX week shut: the
        first tick after the close reads the shut market's own price."""
        w, _ = self._ticks("AAA", FRI_CLOSE, [-2, 3, 8], venue=("forex", ""))
        self.assertEqual(w.rates(), ["11", "11"])


class TheHalfHoursAnswerServesEveryRowTests(_ShutOn, TestCase):
    """THE HALF HOUR'S ANSWER SERVES EVERY ROW OF IT (2026-11-01, review):
    a row the pass reaches long after the read, a second config holding
    the same symbol, a row the batch left out, a batch that failed."""

    def setUp(self):
        super().setUp()
        self.user = _user("rb_reach")
        _etoro_account(self.user)
        self.a = _cfg(self.user, "A")
        self.b = _cfg(self.user, "B")
        _instrument("AAA", "commodity", "COMEX")
        _instrument("BBB", "commodity", "COMEX")

    def _prefetch(self, t):
        from bot_program.asset_engine.base import prefetch_fleet_marks
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            prefetch_fleet_marks()

    def _stamp_at(self, row):
        row.refresh_from_db()
        vm = row.metadata.get("venue_mark") or {}
        return parse_datetime(vm["at"]) if vm.get("at") else None

    def test_a_row_walked_long_after_the_prefetch_is_marked_off_its_read(
            self):
        row = _held(self.a, "AAA")
        w = _Wire(prices={11: 101.0})
        t = _trader(w)
        for m in (0, 31, 62):
            start = SAT + timedelta(minutes=m)
            with self._at(start):
                self._prefetch(t)
            with self._at(start + timedelta(seconds=45)):
                _tick(self.a, t)
            self.assertEqual(self._stamp_at(row), start, m)
        self.assertEqual(w.rates(), ["11", "11", "11"],
                         "one read a half hour: the prefetch's")
        self.assertEqual(_note(self.a, "AAA"), {}, "never clock-managed")

    def test_two_configs_on_one_symbol_both_read_its_half_hour(self):
        first, second = _held(self.a, "AAA"), _held(self.b, "AAA")
        w = _Wire(prices={11: 101.0})
        t = _trader(w)
        with self._at(SAT):
            self._prefetch(t)
        with self._at(SAT + timedelta(seconds=10)):
            _tick(self.a, t)
        with self._at(SAT + timedelta(seconds=55)):
            _tick(self.b, t)
        self.assertEqual(self._stamp_at(first), SAT)
        self.assertEqual(self._stamp_at(second), SAT)
        self.assertEqual(w.rates(), ["11"])

    def test_a_row_the_shut_batch_left_out_takes_the_single_read(self):
        _held(self.a, "AAA")
        left_out = _held(self.a, "BBB")
        w = _Wire(prices={11: 101.0, 22: 102.0}, alone_only={22})
        t = _trader(w)
        with self._at(SAT):
            self._prefetch(t)
        with self._at(SAT + timedelta(seconds=5)):
            _tick(self.a, t)
        self.assertEqual(w.sets(), ["11,22", "22"])
        left_out.refresh_from_db()
        self.assertEqual(left_out.metadata["venue_mark"]["price"], 102.0)
        # and its own answer serves its half hour
        with self._at(SAT + timedelta(minutes=5)):
            self._prefetch(t)
            _tick(self.a, t)
        self.assertEqual(w.sets(), ["11,22", "22"])

    def test_a_failed_shut_batch_says_so_and_the_next_tick_asks_again(self):
        rows = [_held(self.a, s) for s in ("AAA", "BBB")]
        w = _Wire(prices={11: 101.0, 22: 102.0}, status=[503, 503, 200])
        t = _trader(w)
        with self._at(SAT):
            self._prefetch(t)
        with self._at(SAT + timedelta(seconds=1)):
            _tick(self.a, t)
        for s in ("AAA", "BBB"):
            self.assertTrue(_note(self.a, s)["detail"].startswith(
                "open position only clock-managed: the mark could not be "
                "read (BatchFailed: the batched rates read failed (HTTP "
                "503)"), s)
        self.mono.t += 300
        with self._at(SAT + timedelta(minutes=5)):
            self._prefetch(t)
            _tick(self.a, t)
        self.assertEqual(w.sets(), ["11,22", "11,22", "11,22"],
                         "the failed batch, its retry, the next tick's")
        for row, price in zip(rows, (101.0, 102.0)):
            row.refresh_from_db()
            self.assertEqual(row.metadata["venue_mark"]["price"], price)


# ── the cache's ages; the last look and the order never read it ──────────

class TheCacheAgeTests(_RatesOn, TestCase):

    def setUp(self):
        super().setUp()
        self.user = _user("rb_age")
        self.cfg = _cfg(self.user, "G", symbols=["AAA"])
        self.row = _held(self.cfg, "AAA")
        self.wire = _Wire(prices={11: 101.0})
        self.t = _trader(self.wire)
        self.t0 = self.clock.t
        self.t.ticker("AAA")                 # the answer every test reads

    def test_a_mark_takes_an_answer_up_to_thirty_seconds_old(self):
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11"], "read off the cache")
        self.row.refresh_from_db()
        stamped = parse_datetime(self.row.metadata["venue_mark"]["at"])
        self.assertAlmostEqual(stamped.timestamp(), self.t0, places=3,
                               msg="the stamp is dated at the read")
        with self._at(self._later(2)):     # 31 s
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"])

    def test_the_preview_takes_no_cached_answer(self):
        # 2026-11-02 (completes E2): the TAKE TRADE dialog reads the wire,
        # as it did before the cache (this was ..._takes_one_up_to_ten_
        # seconds_old: PREVIEW_MAX_AGE_S, gone); the money rules change
        # nothing a page shows beyond the budget's own command
        from bot_program import manual_trade as mt
        self.assertFalse(hasattr(er, "PREVIEW_MAX_AGE_S"))
        self.clock.t = self.t0 + 9
        with mock.patch(ROUTER, return_value=self.t):
            price, _c, _d, _r, tick = mt._mark_for_detail(
                self.user, self.cfg, "AAA")
        self.assertEqual(price, 101.0)
        self.assertNotIn("cached", tick)
        self.assertEqual(self.wire.rates(), ["11", "11"], "read on the wire")

    def test_the_last_look_never_reads_it(self):
        from bot_program.asset_engine.base import make_bot
        self.clock.t = self.t0 + 1
        make_bot(self.cfg)._last_look(self.t, "AAA", "BUY", 100.0, 98.0,
                                      104.0)
        self.assertEqual(self.wire.rates(), ["11", "11"])

    def test_the_send_and_the_close_button_never_read_it(self):
        from bot_program import manual_trade as mt
        from bot_program.asset_engine.base import make_bot
        self.clock.t = self.t0 + 1
        with mock.patch(ROUTER, return_value=self.t):
            mt._mark_for_detail(self.user, self.cfg, "AAA")
        # the CLOSE button prices through the bot's own _mark_price
        # (manual_close), outside the manage tick
        make_bot(self.cfg)._mark_price(self.row, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11", "11"])

    def test_the_pending_close_mark_reads_the_wire(self):
        """P0 (the drain, the CLOSE button's retry): never a cache read on
        a path between two closes (the budget's rule), so its mark is a
        fresh answer, as before, even beside a 5-second-old one."""
        from bot_program.pending_closes import mark_with_quality
        self.clock.t = self.t0 + 5
        mark, q = mark_with_quality(self.row, self.t)
        self.assertEqual((mark, q), (Decimal("101.0"), {}))
        self.assertEqual(self.wire.rates(), ["11", "11"])

    def test_the_orphan_mark_reads_the_wire(self):
        """P0 (the booking of a venue close): the wire, as before."""
        from bot_program.reconcile_asset import _close_as_orphan
        with self._at(self._later(5)), mock.patch(ROUTER,
                                                  return_value=self.t):
            _close_as_orphan(self.row)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "CLOSED")
        self.assertEqual(self.row.exit_price, Decimal("101.0"))
        self.assertNotIn("exit_mark_cached_age_s", self.row.metadata)
        self.assertEqual(self.wire.rates(), ["11", "11"])

    def test_a_close_booked_at_a_cached_mark_carries_its_age(self):
        from bot_program.asset_engine.base import AssetBot
        with self._at(self._later(12)), \
                mock.patch.object(AssetBot, "_time_stop_hit",
                                  return_value=True), \
                mock.patch.object(AssetBot, "_submit_close_or_raise",
                                  return_value={"orderForClose": {
                                      "orderID": 9, "orderType": 19,
                                      "statusID": 1}}), \
                mock.patch.object(AssetBot, "_cancel_protective_orders",
                                  return_value=True), \
                mock.patch.object(AssetBot, "_reread_account_soon"):
            _tick(self.cfg, self.t)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "CLOSED")
        self.assertEqual(self.row.exit_price, Decimal("101.0"))
        self.assertEqual(self.row.metadata["exit_fill_source"], "mark")
        self.assertEqual(self.row.metadata["exit_mark_cached_age_s"], 12)
        self.assertEqual(self.wire.rates(), ["11"])

    def test_a_fresh_mark_books_no_cached_age(self):
        from bot_program.pending_closes import resolve_exit_fill
        self.row.metadata = dict(self.row.metadata,
                                 exit_mark_cached_age_s=12)
        fill = resolve_exit_fill(self.row, {"orderForClose": {}},
                                 mark=Decimal("101"))
        self.assertIn("exit_mark_cached_age_s", fill["metadata"])
        self.assertIsNone(fill["metadata"]["exit_mark_cached_age_s"],
                          "an earlier attempt's age is cleared")


# ── a cached mark never acts alone ───────────────────────────────────────

def _patches(wire) -> list:
    """The stopLossRate of every PATCH on the wire, in order."""
    return [Decimal(str((kw.get("json") or {}).get("stopLossRate")))
            for method, _url, kw in wire.calls if method == "PATCH"]


class TheCachedMarkNeverActsAloneTests(_RatesOn, TestCase):
    """A STOP MOVE, A CARE CLOSE OR A CHANGE OF THE CARE'S STATE DECIDED ON
    A CACHED MARK IS DECIDED AGAIN ON THE WIRE FIRST (2026-11-01, review):
    110 is cached at t0, the market falls to 108 (inside the stock class's
    3% jump bar, so mark_sanity takes the fresh print), and the row's tick
    comes 29 s later. Entry 100, sent stop 98 (R = 2)."""

    def setUp(self):
        super().setUp()
        self.user = _user("rb_acts")
        self.cfg = _cfg(self.user, "G", symbols=["AAA"])
        self.row = _held(self.cfg, "AAA")
        meta = dict(self.row.metadata, protective_trade_id="p-AAA")
        self.row.metadata = meta
        self.row.save()
        self.wire = _Wire(prices={11: 110.0})
        self.t = _trader(self.wire)

    def _knobs(self, **extras):
        self.cfg.extras = extras
        self.cfg.save(update_fields=["extras"])

    def _seed_then(self, now_price, *, seeded=110.0):
        self.wire.prices[11] = seeded
        self.t.ticker("AAA")              # the answer cached at t0
        self.wire.prices[11] = now_price  # the market meanwhile

    def test_a_trail_is_sent_off_the_wire_never_off_a_cached_high(self):
        self._knobs(trail_pct=1)
        self._seed_then(108.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"],
                         "one fresh read before the stop move")
        self.assertEqual(_patches(self.wire), [Decimal("106.92")],
                         "108 less 1%, as the row's own read gave before "
                         "the cache — never 108.9, above the market")
        self.row.refresh_from_db()
        self.assertEqual(self.row.stop_loss, Decimal("106.92"))

    def test_the_care_decides_on_the_wire_and_keeps_no_cached_peak(self):
        from tests.test_aragorn import _switch
        _switch("aragorn")
        self._knobs(trail_pct=3)          # the knobs ride the same read
        self._seed_then(108.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"],
                         "ONE fresh read for the care and the knobs both")
        self.assertEqual(_patches(self.wire), [Decimal("106.5")],
                         "the care's lock off 108 (+4R less 0.75R) — never "
                         "108.5 off the cached 110, above the market")
        self.row.refresh_from_db()
        self.assertEqual(self.row.metadata["care"]["peak"], 108.0)

    def _accepted(self, price, minutes_ago=5):
        """The mark sanity's state from the row's last tick: `price`
        accepted `minutes_ago` before the tick this test runs."""
        at = (self._later(29) - timedelta(minutes=minutes_ago)).isoformat()
        self.row.metadata = dict(self.row.metadata, care={
            "last_mark": price, "last_mark_at": at, "mark_same_since": at})
        self.row.save()

    def test_the_wires_read_is_judged_as_the_rows_own_read_was(self):
        """The wire's read is judged by the mark sanity against the state
        from BEFORE the cached print, as the row's own read was before the
        cache: 110 cached, 104 on the wire 29 s later, no mark accepted
        before — 104 is the row's first mark and moves the trail (104 less
        3%), never a jump from the cached 110 nor a trail off it."""
        self._knobs(trail_pct=3)
        self._seed_then(104.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"])
        self.assertEqual(_patches(self.wire), [Decimal("100.88")],
                         "never 106.7 off 110")
        self.assertNotEqual(_note(self.cfg, "AAA").get("code"),
                            "suspect_mark")
        self.row.refresh_from_db()
        self.assertEqual(self.row.metadata["care"]["last_mark"], 104.0)

    def test_a_fresh_read_past_the_jump_bar_waits_for_its_second_print(self):
        """100 accepted 5 min before the tick, 102.5 cached (2.5%, inside
        the stock class's 3% bar), 105.5 on the wire: 5.5% from the last
        mark the row's own read was judged against — held, as before the
        cache, however small its step from the cached print (2.9%)."""
        self._knobs(trail_pct=1)
        self._accepted(100.0)
        self._seed_then(105.5, seeded=102.5)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"])
        self.assertEqual(_patches(self.wire), [],
                         "never 104.445 off a print the bar holds, nor "
                         "101.475 off the cached one")
        self.assertEqual(_note(self.cfg, "AAA")["code"], "suspect_mark")
        self.row.refresh_from_db()
        self.assertEqual(self.row.metadata["care"]["last_mark"], 100.0,
                         "the last mark accepted is the one before the tick")
        self.assertEqual(self.row.stop_loss, Decimal("98"))

    def test_a_fresh_read_the_bar_passes_is_acted_on(self):
        """105 accepted 5 min before, 108 cached (2.9%), 104 on the wire:
        1% from the last mark — passed, as the row's own read was, however
        far it lands from the cached print (3.7%)."""
        self._knobs(trail_pct=1)
        self._accepted(105.0)
        self._seed_then(104.0, seeded=108.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"])
        self.assertEqual(_patches(self.wire), [Decimal("102.96")],
                         "104 less 1% — never 106.92 off the cached 108")
        self.row.refresh_from_db()
        self.assertEqual(self.row.stop_loss, Decimal("102.96"))

    def test_the_mirrors_retry_of_a_lock_is_decided_on_the_wire(self):
        """The venue still holds the sent stop (98) under the care's soft
        stop of 106.5 (+4R less 0.75R off a 108 peak), last asked 40 min
        ago: the mirror asks again this tick. 107 cached changes nothing;
        109 on the wire is a new peak, and the row's own read would have
        sent the trail it makes (107.5): that is what goes."""
        from tests.test_aragorn import _switch
        _switch("aragorn")
        asked = (self._later(29) - timedelta(minutes=40)).isoformat()
        self.row.metadata = dict(self.row.metadata, care={
            "peak": 108.0, "worst": 100.0, "soft_stop": 106.5,
            "soft_why": "trail", "venue_asked_for": 106.5,
            "venue_asked_at": asked, "venue_stop_refusal": "refused",
            "since": "2026-10-31T00:00:00+00:00"})
        self.row.save()
        self._seed_then(109.0, seeded=107.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"])
        self.assertEqual(_patches(self.wire), [Decimal("107.5")],
                         "never the unchanged 106.5 the cached 107 kept")
        self.row.refresh_from_db()
        self.assertEqual(self.row.metadata["care"]["peak"], 109.0)
        self.assertEqual(self.row.stop_loss, Decimal("107.5"))

    def test_a_care_close_is_decided_on_the_wire(self):
        from bot_program.asset_engine.base import AssetBot
        from tests.test_aragorn import _switch
        _switch("aragorn")
        # a soft stop of 102 the venue was asked for (never again before
        # 2099): a mark at or under 102 closes the row
        self.row.metadata = dict(self.row.metadata, care={
            "peak": 104.0, "worst": 100.0, "soft_stop": 102.0,
            "soft_why": "trail", "venue_asked_for": 102.0,
            "venue_asked_at": "2099-01-01T00:00:00+00:00",
            "since": "2026-10-31T00:00:00+00:00"})
        self.row.save()
        self._seed_then(103.0, seeded=101.5)
        closes = []

        def spy(bot, trade, price, client, reason=""):
            closes.append((str(price), reason))
            return True
        with self._at(self._later(29)), \
                mock.patch.object(AssetBot, "_close_trade", spy), \
                mock.patch("bot_program.position_care._venue_still_holds",
                           return_value=True):
            _tick(self.cfg, self.t)
        self.assertEqual(closes, [], "103 on the wire: nothing to close")
        self.assertEqual(self.wire.rates(), ["11", "11"])

    def test_a_care_close_the_wire_confirms_books_the_wires_price(self):
        """101.5 cached and 101.8 on the wire both cross the soft stop of
        102: the close goes, decided and booked on the wire's read (no
        cached age on the row), as the row's own read closed it before."""
        from bot_program.asset_engine.base import AssetBot
        from tests.test_aragorn import _switch
        _switch("aragorn")
        self.row.metadata = dict(self.row.metadata, care={
            "peak": 104.0, "worst": 100.0, "soft_stop": 102.0,
            "soft_why": "trail", "venue_asked_for": 102.0,
            "venue_asked_at": "2099-01-01T00:00:00+00:00",
            "since": "2026-10-31T00:00:00+00:00"})
        self.row.save()
        self._seed_then(101.8, seeded=101.5)
        with self._at(self._later(29)), \
                mock.patch.object(AssetBot, "_submit_close_or_raise",
                                  return_value={"orderForClose": {
                                      "orderID": 9, "orderType": 19,
                                      "statusID": 1}}), \
                mock.patch.object(AssetBot, "_cancel_protective_orders",
                                  return_value=True), \
                mock.patch.object(AssetBot, "_reread_account_soon"), \
                mock.patch("bot_program.position_care._venue_still_holds",
                           return_value=True):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11", "11"])
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "CLOSED")
        self.assertEqual(self.row.exit_price, Decimal("101.8"))
        self.assertIsNone(self.row.metadata.get("exit_mark_cached_age_s"))

    def test_a_cached_mark_that_moves_nothing_asks_nothing_more(self):
        self._knobs(trail_pct=3)
        self._seed_then(101.0, seeded=101.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11"], "read off the cache")
        self.assertEqual(_patches(self.wire), [])

    def test_a_care_that_changes_nothing_asks_nothing_more(self):
        """The care watched on the cached mark: its peak, its soft stop and
        the venue's stop all stand, so no fresh read is asked."""
        from tests.test_aragorn import _switch
        _switch("aragorn")
        care = {"peak": 110.0, "worst": 100.0, "soft_stop": 108.5,
                "soft_why": "trail", "venue_stop": 108.5,
                "since": "2026-10-31T00:00:00+00:00"}
        self.row.metadata = dict(self.row.metadata, care=care)
        self.row.stop_loss = Decimal("108.5")
        self.row.save()
        self._seed_then(109.0, seeded=109.0)
        with self._at(self._later(29)):
            _tick(self.cfg, self.t)
        self.assertEqual(self.wire.rates(), ["11"], "read off the cache")
        self.assertEqual(_patches(self.wire), [])
        self.row.refresh_from_db()
        self.assertEqual({k: self.row.metadata["care"].get(k) for k in care},
                         care)

    def test_a_fresh_read_that_fails_moves_nothing_and_is_one_failure(self):
        self._knobs(trail_pct=3)
        self._seed_then(104.0)
        self.wire.status = [503]
        with self._at(self._later(29)), mock.patch("time.sleep"):
            _tick(self.cfg, self.t)
        self.assertEqual(_patches(self.wire), [], "no move on a cached high")
        self.assertEqual(self.wire.rates(), ["11", "11", "11"],
                         "the fresh read and its one retry")
        self.assertEqual(
            len(vh._load(vh._key("etoro", "live"))["failures"]), 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.stop_loss, Decimal("98"))


# ── an order is never priced off the cache or a batch alone ──────────────

class TheSnapshotPricedOrderTests(TestCase):
    """A PROPOSAL PRICED OFF THE SHARED CACHE OR A BATCH IS NEVER ORDERED ON
    THAT PRICE ALONE (2026-11-01, review): its last look fails closed — an
    unreadable look, or one with no price, sends nothing. A proposal read
    on the wire keeps today's rule (an unreadable look still sends). The
    real adapter over a fake wire (tests.test_etoro_leverage)."""

    RATES_500 = ("GET", "/rates", 500, {})
    RATES_ZERO = ("GET", "/rates", 200, {"rates": [
        {"bid": 0, "ask": 0, "lastExecution": 0}]})
    RATES_FRESH = ("GET", "/rates", 200, {"rates": [
        {"bid": 99.99, "ask": 100.01, "lastExecution": 100.0}]})

    def setUp(self):
        from tests.test_etoro_leverage import _account, _book
        from tests.test_execution_trust import _cfg as _live_cfg
        from tests.test_execution_trust import _instrument as _inst
        from tests.test_execution_trust import _signal
        self.user = _user("rb_order")
        self.cfg = _live_cfg(self.user, name="ORD")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_inst(), rule="rb_order_rule")
        self.signal_for = lambda s: _signal(_inst(s), rule="rb_order_rule")
        _book(self.user)
        _account(self.user, cash=100000)
        for p in (mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                             frozenset({"stock"})),
                  mock.patch.object(er, "CACHE", True)):
            p.start()
            self.addCleanup(p.stop)
        cache.clear()
        er.reset()
        self.addCleanup(er.reset)
        self.addCleanup(cache.clear)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _wire(self, rates):
        from tests.test_etoro_client import SEARCH_AAPL
        from tests.test_etoro_leverage import POSTED, _etoro
        t, fake = _etoro([SEARCH_AAPL, rates, POSTED])
        t._ids["AAPL"] = 1001
        return t, fake

    def _rates(self, fake) -> list:
        return [c for c in fake.calls
                if c[0] == "GET" and "/instruments/rates" in c[1]]

    def _run(self, t, *, symbol="AAPL", bot=None):
        from bot_program.asset_engine.stock_bot import StockBot
        bot = bot or StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=t):
            cand = bot.propose_entry(symbol)
        self.assertIsNotNone(cand)
        return bot, cand

    def _execute(self, bot, t, cand):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return bot.execute_entry(cand)

    def _note(self, symbol="AAPL"):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)[symbol]

    def _cached(self, look):
        """A candidate that carries a cached quote's age, as a proposal
        priced off the shared cache did until 2026-11-02 (one an older
        process proposed, across a deploy): its last look still fails
        closed. A proposal itself reads the wire since, whatever the cache
        holds (test_a_proposal_is_priced_on_the_wire_whatever_the_cache_
        holds). The look answers `look`."""
        t, fake = self._wire(self.RATES_FRESH)
        bot, cand = self._run(t)
        self.assertEqual(len(self._rates(fake)), 1, "the proposal's own read")
        cand.level_meta = dict(cand.level_meta, proposal_quote_age_s=25.0)
        fake.routes.insert(0, look)
        return bot, t, fake, cand

    def test_a_proposal_is_priced_on_the_wire_whatever_the_cache_holds(self):
        """2026-11-02 (completes E2, review): an answer another reader
        received 25 s ago at 99.80 is in the cache; the proposal reads the
        wire (100.0) and is built on it, with no snapshot's age."""
        t, fake = self._wire(self.RATES_FRESH)
        er.put(t._world(), 1001, {"lastPrice": "99.80", "bid": "99.79",
                                  "ask": "99.81"}, at=er._now() - 25)
        _bot, cand = self._run(t)
        self.assertEqual(len(self._rates(fake)), 1, "read on the wire")
        self.assertEqual(cand.market_price, 100.0)
        self.assertNotIn("proposal_quote_age_s", cand.level_meta)
        self.assertNotIn("proposal_quote_batched", cand.level_meta)

    def test_a_cached_proposal_whose_look_cannot_read_sends_nothing(self):
        from bot_program.asset_engine import skips
        from tests.test_etoro_leverage import _order_posts
        bot, t, fake, cand = self._cached(self.RATES_500)
        self.assertIsNone(self._execute(bot, t, cand))
        self.assertEqual(_order_posts(fake), [], "no order on a cached price")
        self.assertEqual(len(self._rates(fake)), 1 + 2,
                         "the proposal's read, then the look and its retry")
        note = self._note()
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertTrue(note["detail"].startswith(
            "AAPL: the last look could not read the quote"), note)
        self.assertIn("this look fails closed", note["detail"])

    def test_a_cached_proposal_whose_look_reads_no_price_sends_nothing(self):
        from tests.test_etoro_leverage import _order_posts
        bot, t, fake, cand = self._cached(self.RATES_ZERO)
        self.assertIsNone(self._execute(bot, t, cand))
        self.assertEqual(_order_posts(fake), [])
        self.assertIn("read a quote with no price", self._note()["detail"])

    def test_a_cached_proposal_whose_look_reads_is_sent_on_the_look(self):
        from tests.test_etoro_leverage import _order_posts
        bot, t, fake, cand = self._cached(self.RATES_FRESH)
        self.assertIsNotNone(self._execute(bot, t, cand))
        self.assertEqual(len(_order_posts(fake)), 1)

    def test_a_batched_proposal_whose_look_cannot_read_sends_nothing(self):
        # a candidate carrying a batch's mark, as a proposal priced by a
        # batch did until 2026-11-02 (an older process's): the same rule.
        # A proposal reads its own rate on the wire since
        # (TheProposalReadsTheWireTests: one read each, never a batch).
        from tests.test_etoro_leverage import _order_posts
        t, fake = self._wire(self.RATES_FRESH)
        bot, cand = self._run(t)
        self.assertNotIn("proposal_quote_batched", cand.level_meta)
        fake.routes.insert(0, self.RATES_500)
        cand.level_meta = dict(cand.level_meta, proposal_quote_batched=True)
        self.assertIsNone(self._execute(bot, t, cand))
        self.assertEqual(_order_posts(fake), [])

    def test_a_proposal_read_on_the_wire_keeps_todays_rule(self):
        """The cache on but empty: the proposal's own single read is the
        wire's, and an unreadable look still sends, as before the cache."""
        from tests.test_etoro_leverage import _order_posts
        t, fake = self._wire(self.RATES_FRESH)
        bot, cand = self._run(t)
        self.assertEqual(len(self._rates(fake)), 1)
        self.assertNotIn("proposal_quote_age_s", cand.level_meta)
        self.assertNotIn("proposal_quote_batched", cand.level_meta)
        fake.routes.insert(0, self.RATES_500)
        self.assertIsNotNone(self._execute(bot, t, cand))
        self.assertEqual(len(_order_posts(fake)), 1)


class TheTicketShowsTheAgeTests(_RatesOn, TestCase):
    """The TAKE TRADE preview, on the real adapter: it reads the wire, as
    the send's own previews do (2026-11-02, completes E2: it took a price
    off the shared cache up to 10 s old, and said its age where no page
    showed it; a page shows what it showed before the budget)."""

    def setUp(self):
        super().setUp()
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _quote)
        self.user = _user("rb_ticket")
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"crypto"}))
        p.start()
        self.addCleanup(p.stop)

    def _preview(self, t):
        from bot_program.manual_trade import preview_asset_trade
        with mock.patch(ROUTER, return_value=t):
            return preview_asset_trade(self.user, self.inst, "BUY")

    def test_the_preview_reads_the_wire_beside_a_fresh_cached_price(self):
        # was ..._says_how_old_its_cached_price_is (4.0 s, one read)
        w = _Wire(prices={100000: 60000.0})
        t = _trader(w, env="demo", ids={"BTCUSD": 100000})
        t.ticker("BTCUSD")
        self.clock.t += 4
        out = self._preview(t)
        self.assertIsNone(out.get("mark_cached_age_s"), out.get("error"))
        self.assertEqual(w.rates(), ["100000", "100000"])

    def test_a_fresh_preview_price_has_no_cached_age(self):
        w = _Wire(prices={100000: 60000.0})
        t = _trader(w, env="demo", ids={"BTCUSD": 100000})
        out = self._preview(t)
        self.assertIsNone(out.get("mark_cached_age_s"), out.get("error"))
        self.assertEqual(w.rates(), ["100000"])

    def test_the_sends_own_previews_read_the_wire(self):
        from bot_program import manual_trade as mt
        seen = []
        real = mt._mark_for_detail

        def spy(*a, **kw):
            seen.append(kw.get("max_age_s", 0))
            return real(*a, **kw)
        w = _Wire(prices={100000: 60000.0})
        t = _trader(w, env="demo", ids={"BTCUSD": 100000})
        with mock.patch.object(mt, "_mark_for_detail", spy), \
                mock.patch(ROUTER, return_value=t):
            mt._preview(self.user, self.inst, "BUY", ask_reread=False)
            mt.preview_asset_trade(self.user, self.inst, "BUY")
        # the dialog's own preview reads the wire too since 2026-11-02 (it
        # asked PREVIEW_MAX_AGE_S, 10 s)
        self.assertEqual(seen, [0, 0])


# ── every money path still refuses a 0 ───────────────────────────────────

class TheZeroTests(_RatesOn, TestCase):

    def setUp(self):
        super().setUp()
        self.user = _user("rb_zero")
        _etoro_account(self.user)
        self.cfg = _cfg(self.user, "Z", symbols=["AAA", "BBB"])

    def test_a_zero_row_in_the_snapshot_is_never_a_mark(self):
        zero, priced = _held(self.cfg, "AAA"), _held(self.cfg, "BBB")
        w = _Wire(prices={11: 0, 22: 102.0})
        _tick(self.cfg, _trader(w))
        self.assertEqual(w.sets(), ["11,22"])
        self.assertEqual(_note(self.cfg, "AAA")["detail"],
                         "open position only clock-managed: the broker "
                         "priced it at 0")
        zero.refresh_from_db()
        priced.refresh_from_db()
        self.assertNotIn("venue_mark", zero.metadata)
        self.assertEqual(priced.metadata["venue_mark"]["price"], 102.0)

    def test_a_zero_in_the_proposals_read_is_never_an_entry(self):
        # each proposal reads its own rate on the wire since 2026-11-02
        # (this read one batch, "11,22", and was ..._proposals_snapshot_...)
        from bot_program.asset_engine import runner, skips
        w = _Wire(prices={11: 0, 22: 102.0})
        candidates = []
        with mock.patch(ROUTER, return_value=_trader(w)), \
                mock.patch("bot_program.asset_engine.stock_bot.StockBot"
                           ".decide", return_value=_buy()), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           ".can_open_new", return_value=(True, "")):
            runner._propose_phase(self.cfg, signal_stats={},
                                  candidates=candidates,
                                  not_desked={"paper": [], "live": []},
                                  summaries=[])
        self.assertEqual(w.rates(), ["11", "22"])
        self.assertEqual([c.symbol for c in candidates], ["BBB"])
        note = _note(self.cfg, "AAA")
        self.assertEqual((note["code"], note["detail"]),
                         (skips.NO_PRICE, "ticker returned 0"))

    def _cached_zero(self):
        w = _Wire(prices={11: 0})
        t = _trader(w)
        t.ticker("AAA")
        self.clock.t += 5
        return t, w

    def test_a_zero_never_books_a_pending_close(self):
        from bot_program.pending_closes import mark_with_quality
        t, w = self._cached_zero()
        row = _held(self.cfg, "AAA")
        mark, _q = mark_with_quality(row, t)
        self.assertIsNone(mark)
        self.assertEqual(w.rates(), ["11", "11"], "the wire's zero")

    def test_a_zero_never_prices_an_orphan(self):
        from bot_program.reconcile_asset import _close_as_orphan
        t, w = self._cached_zero()
        row = _held(self.cfg, "AAA")
        with mock.patch(ROUTER, return_value=t):
            _close_as_orphan(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSED")
        self.assertIsNone(row.pnl, "unpriced: never the entry's zero")
        self.assertTrue(row.metadata.get("exit_price_unavailable"))
        self.assertNotIn("exit_mark_cached_age_s", row.metadata)

    def test_a_cached_zero_is_no_ticket_price(self):
        from bot_program import manual_trade as mt
        t, _w = self._cached_zero()
        # the preview's own 10 s, written out: PREVIEW_MAX_AGE_S went with
        # the dialog's cache read (2026-11-02); the reader stays
        with mock.patch(ROUTER, return_value=t):
            price, _c, _d, reason, _t = mt._mark_for_detail(
                self.user, self.cfg, "AAA", max_age_s=10)
        self.assertIsNone(price)
        self.assertEqual(reason, "answered no rate")

    def test_the_cache_never_turns_a_zero_into_a_price(self):
        er.put("live", 11, {"lastPrice": "0", "symbol": "AAA"})
        got = er.get("live", 11, symbol="AAA", max_age_s=30)
        self.assertEqual(got["lastPrice"], "0")
        self.assertNotIn("bid", got)


# ── the switches ─────────────────────────────────────────────────────────

class TheSwitchTests(SimpleTestCase):

    def test_the_suite_runs_with_the_cache_and_the_cadence_off(self):
        self.assertIs(er.CACHE, False)
        self.assertIs(er.SHUT_CADENCE, False)
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_rates.CACHE = False", src)
        self.assertIn("_etoro_rates.SHUT_CADENCE = False", src)

    def test_the_batch_waits_for_its_measurement_but_not_in_the_suite(self):
        # 2026-11-02 (completes E2): on in production, off for the suite,
        # whose batch tests read the batch as E2 sent it; TheBatchWaitsFor
        # ItsMeasurementTests turns it on
        import inspect
        self.assertIs(er.MEASURED_FIRST, False)
        self.assertIn("\nMEASURED_FIRST = True\n", inspect.getsource(er))
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_rates.MEASURED_FIRST = False", src)

    def test_the_constants(self):
        # an answer lives the cadence's half hour; each reader bounds the
        # age it takes (2026-11-01, review: the half hour's answer is what
        # a shut market's marks read)
        self.assertEqual((er.CACHE_TTL_S, er.MARK_MAX_AGE_S), (1800, 30))
        # 2026-11-02 (completes E2): no proposal and no TAKE TRADE preview
        # reads the cache any more (an order is never priced from it, and
        # a page shows what it showed); their ages, 30 and 10, are gone
        for gone in ("PROPOSAL_MAX_AGE_S", "PREVIEW_MAX_AGE_S"):
            self.assertFalse(hasattr(er, gone), gone)
        self.assertEqual(er.CACHE_TTL_S, er.SHUT_EVERY_S)
        self.assertEqual(er.BATCH_MAX_IDS, 20)
        self.assertEqual(er.UNPROVEN_TTL_S, 24 * 3600)
        self.assertEqual((er.SHUT_EVERY_S, er.SHUT_REOPEN_EARLY_S),
                         (1800, 600))
        self.assertEqual(er.SHUT_MIN_SPAN_S, 24 * 3600)
        # a subset of the entry gate's classes: stocks and ETFs out, eToro
        # trades US share CFDs out of the NYSE's session (2026-11-01,
        # review)
        self.assertEqual(er.SHUT_CADENCE_CLASSES,
                         frozenset({"forex", "commodity"}))
        self.assertLess(er.SHUT_CADENCE_CLASSES, et.SHUT_CLASSES)
        for cls in ("crypto", "stock", "etf", "index"):
            self.assertNotIn(cls, er.SHUT_CADENCE_CLASSES)

    def test_the_batch_is_a_market_read_and_a_pause_site(self):
        self.assertEqual(eb.family_of("rates"), eb.MARKET)
        self.assertIn("rates", ec.RATE_PAUSE_SITES)


class TheSwitchOffTests(TestCase):

    def test_off_every_row_is_read_alone_as_before(self):
        cfg = _cfg(_user("rb_off"), "O")
        _held(cfg, "AAA")
        _held(cfg, "BBB")
        w = _Wire(prices={11: 101.0, 22: 102.0})
        _tick(cfg, _trader(w))
        self.assertEqual(sorted(w.rates()), ["11", "22"])


# ── the operator's measurement ───────────────────────────────────────────

class TheBatchWaitsForItsMeasurementTests(_RatesOn, TestCase):
    """2026-11-02 (completes E2, review): the plan landed the batch "only
    after its demo measurement" (one call with two ids, the row keys and
    their order recorded); E2 sent it from the first pass, an untrusted
    answer turning it off by itself. Nothing is sent in batch now until the
    operator's measurement (manage.py etoro_rates_shape, the demo key by
    default) has read an answer the parser trusts: every symbol takes the
    single read meanwhile, as before the batch, and an answer the batch
    itself does not trust still turns it off for a day."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(er, "MEASURED_FIRST", True)
        p.start()
        self.addCleanup(p.stop)
        er.forget_proof()
        self.addCleanup(er.forget_proof)

    def test_unmeasured_nothing_is_sent_in_batch(self):
        w = _Wire(prices={11: 101.0, 22: 102.0})
        got = _trader(w).tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), [], "nothing sent")
        for s in ("AAA", "BBB"):
            self.assertIsInstance(got[s], er.BatchUnproven)
            self.assertIn("wait for the operator's measurement", str(got[s]))

    def test_unmeasured_every_row_is_read_alone(self):
        cfg = _cfg(_user("rb_unmeasured"), "U")
        for s in ("AAA", "BBB"):
            _held(cfg, s)
        w = _Wire(prices={11: 101.0, 22: 102.0})
        _tick(cfg, _trader(w))
        self.assertEqual(sorted(w.rates()), ["11", "22"])

    def test_a_proof_lets_the_batch_go(self):
        er.prove("demo", "rates: a list of 2")
        self.assertEqual(er.proven()["world"], "demo")
        w = _Wire(prices={11: 101.0, 22: 102.0})
        got = _trader(w).tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), ["11,22"])
        self.assertEqual(got["BBB"]["lastPrice"], "102.0")

    def test_an_untrusted_answer_still_turns_a_proven_batch_off(self):
        er.prove("demo", "rates: a list of 2")
        w = _Wire(body=lambda ids: {"rates": [{"bid": 1.0}, {"bid": 2.0}]})
        t = _trader(w)
        t.tickers(["AAA", "BBB"])
        self.assertIsNotNone(er.unproven())
        t.tickers(["AAA", "BBB"])
        self.assertEqual(w.rates(), ["11,22"], "off for the day after it")


class TheShapeCommandTests(_RatesOn, TestCase):

    API, KEY = "API-SECRET-0042", "USER-SECRET-0043"

    def setUp(self):
        super().setUp()
        from bot_program.models import EtoroAccount
        self.user = _user("rb_cmd")
        acct = EtoroAccount(user=self.user, demo=True)
        acct.set_credentials(self.API, self.KEY)
        acct.save()

    def _run(self, wire, *args):
        out = StringIO()
        with mock.patch.object(ec.EtoroTrader, "_sess",
                               lambda self: wire):
            call_command("etoro_rates_shape", "--user", "rb_cmd", *args,
                         stdout=out)
        return out.getvalue()

    def test_one_get_with_two_ids_prints_keys_order_and_fields_only(self):
        w = _Wire(body=lambda ids: {"rates": [
            {"instrumentID": ids[1], "bid": 123.456789, "ask": 123.456999,
             "lastExecution": 123.456888, "date": "2026-11-01T10:00:00Z"},
            {"instrumentID": ids[0], "bid": 9.87654321, "ask": None}]})
        text = self._run(w)
        self.assertEqual(w.rates(), ["18,100005"], "one GET, two ids")
        self.assertIn("world demo", text)
        self.assertIn("rates: a list of 2", text)
        self.assertIn("row 1: instrumentID 100005", text)
        self.assertIn("row 2: instrumentID 18", text)
        self.assertIn("ask number, bid number, date text, instrumentID "
                      "number, lastExecution number", text)
        self.assertIn("ask null, bid number, instrumentID number", text)
        self.assertIn("the rows came back REORDERED", text)
        self.assertIn("trusted", text)
        for secret in ("123.456", "9.876", self.API, self.KEY):
            self.assertNotIn(secret, text)
        # 2026-11-02: the trusted answer is the proof the batch waits for
        held = er.proven()
        self.assertEqual((held or {}).get("world"), "demo")
        self.assertIn("proof    written: the batch may be sent from now on",
                      text)
        for secret in (self.API, self.KEY):
            self.assertNotIn(secret, str(held))

    def test_an_untrusted_shape_is_said_and_marks_nothing(self):
        w = _Wire(body=lambda ids: {"rates": [{"bid": 1.0}, {"bid": 2.0}]})
        text = self._run(w, "--world", "live", "--ids", "17,18")
        self.assertEqual(w.rates(), ["17,18"])
        self.assertIn("world live", text)
        self.assertIn("NOT trusted: a row with no instrumentId of its own",
                      text)
        self.assertIsNone(er.unproven(), "a measurement marks nothing")
        self.assertIsNone(er.proven(), "and proves nothing")

    def test_no_row_at_all_is_said_as_no_row(self):
        w = _Wire(body=lambda ids: {"rates": []})
        text = self._run(w)
        self.assertIn("NOT trusted: no row came back for any of the 2 ids "
                      "asked", text)
        self.assertNotIn("parser   trusted", text)

    def test_a_429_or_a_5xx_is_said_as_the_batch_answers_it(self):
        """A failed answer is no distrust: the adapter's batch answers
        BatchFailed (one failure noted, its symbols not asked again for
        30 s) and stays on. The measurement itself is a background read:
        it notes nothing on the world's health and starts no pause."""
        p = mock.patch.object(ec, "RATE_PAUSE", True)
        p.start()
        self.addCleanup(p.stop)
        eb.reset()
        self.addCleanup(eb.reset)
        for code, sent in ((429, 1), (503, 2)):
            with self.subTest(code=code):
                w = _Wire(prices={18: 1.0, 100005: 2.0}, status=code)
                with mock.patch("time.sleep"):
                    text = self._run(w)
                self.assertEqual(len(w.rates()), sent,
                                 "a 5xx is asked once more, a 429 never")
                self.assertIn(f"HTTP {code}", text)
                self.assertIn("the batch stays on", text)
                self.assertNotIn("unproven for 24 h", text)
                self.assertIsNone(er.unproven())
                self.assertIsNone(er.proven(), "a failure proves nothing")
                self.assertEqual(vh._load(vh._key("etoro", "demo")), {},
                                 "a background read notes nothing")
                t = ec.EtoroTrader(self.API, self.KEY, env="demo")
                self.assertEqual(t.rate_pause_s(), 0.0, "and grants no pause")

    def test_it_goes_through_the_budget_at_p5(self):
        from tests.test_etoro_budget import _fill
        eb.reset()
        self.addCleanup(eb.reset)
        p = mock.patch.object(eb, "BUDGET", True)
        p.start()
        self.addCleanup(p.stop)
        # the command's key pair is the stored one: its budget is that key's
        _fill(eb.key_hash(self.KEY), eb.MARKET, eb.limit(eb.MARKET, eb.P5))
        w = _Wire(prices={18: 1.0, 100005: 2.0})
        text = self._run(w)
        self.assertEqual(w.rates(), [])
        self.assertIn("answer   not asked — eToro budget: market 30/60", text)
        self.assertIn("(P5 candles)", text)
        self.assertNotIn(self.KEY, text)

    def test_it_is_a_terminal_command_off_the_ops_page(self):
        # 2026-11-02 (completes E2, review): it was registered in the ops
        # catalogue, which put it on /ops/ and in the Wall's command
        # count: a change of what a page shows beyond the budget's own
        # command. It is named exempt now, with its reason; the budget's
        # own command stays listed
        from core import ops_commands
        self.assertIsNone(ops_commands.get("etoro_rates_shape"))
        self.assertIn("etoro_rates_shape", ops_commands.EXEMPT)
        self.assertIn("terminal", ops_commands.EXEMPT["etoro_rates_shape"])
        self.assertNotIn("etoro_rates_shape", ops_commands.runnable_names())
        self.assertIsNotNone(ops_commands.get("etoro_budget"))
