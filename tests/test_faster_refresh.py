"""THE FASTER REFRESH (2026-11-06). The operator, after Sauron showed an
open eToro position's P&L unlike eToro's own (its forex marked from a
keyless yfinance poll every 600 s, with no bid and no ask): "On ne peut
aussi encore augmenter to the maximum le taux de refresh des valeurs et
de eToro surtout svp?".

  * eToro's own quotes for the open real positions, every 30 s
    (bot_program/etoro_quotes.py, the beat refresh-etoro-quotes): eToro's
    bid, ask and last for the instruments of the OPEN REAL eToro rows,
    written to LiveQuote under the source "etoro", which outranks yfinance
    while fresh (market_data/quotes.py). At P3 in the eToro request budget
    (the marks' priority), never P1; ONE batched read once the operator's
    measurement proved the batch, one read an instrument otherwise, at most
    SINGLE_READS_PER_PASS a pass, stalest first. A refusal, a 429, a 5xx, a
    transport failure or the shared pause ends the pass, never retried in a
    loop; nothing is asked while eToro is sick, for a market the shut
    cadence holds shut, or for an instrument whose platform quote is
    another instrument (Yahoo's front-month future, a cash index).
  * The eToro account sync every 60 s (300 s before): the cells, the
    equity and the holdings every pass, the equity history row at most
    every five minutes (the readers that walk it read what they read), the
    stall alert and the alarm after fifteen missed passes (fifteen
    minutes, as three passes were), IBKR and Saxo still after three.
  * The reconcile stays every 5 minutes: its eToro cost (one book a pass)
    would allow every 2, but each pass also sweeps the keyed Saxo and IBKR
    books (no eToro budget meters them), sends a P0 order read for each
    unanswered miss, and writes the bots' component row, which the digest
    and /day/ judge against its most frequent writer: at */2 the
    reconcile, not the 300 s tick, would answer for it.
  * The forex poll every 300 s (600 s before): it asks Yahoo one pair at a
    time (three requests for each pair's .info), so not the 60 s a batched
    call could have had; 300 s is the floor the code calls a polite
    yfinance citizen (tests/test_data_quality.py), the commodity and index
    pollers' cadence.

The suite runs with the eToro budget, the 429 pause, the rates cache and
the shut cadence OFF (tests/__init__.py); the tests below turn on what
they pin.

Run with:  python manage.py test tests.test_faster_refresh
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from celery.schedules import crontab
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import venue_health as vh
from bot_program.engine import etoro_budget as eb
from bot_program.engine import etoro_client as ec
from bot_program.engine import etoro_rates as er
from tests.test_etoro_rates_batch import (IDS, KH, SAT, USER_KEY, _Clock,
                                          _ShutOn, _Wire, _cfg, _held,
                                          _instrument, _trader)

CLIENT_SEAM = "bot_program.etoro_quotes._client_for"


def _beat(key):
    from config.celery import app
    return app.conf.beat_schedule[key]


def _components(**on):
    from core.platform_control import PlatformComponent
    for key in ("platform_master", "broker_account_sync"):
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key, "category": "system",
                               "is_enabled": on.get(key, True)})


def _account(user, *, demo=False):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(
        user=user, demo=demo, label="Main", is_primary_for_stocks=True,
        is_primary_for_forex=True, is_primary_for_commodity=True,
        is_primary_for_crypto=True)
    acct.set_credentials("api-k", USER_KEY)
    acct.save()
    return acct


def _quote(symbol):
    from market_data.models import LiveQuote
    return LiveQuote.objects.filter(instrument__symbol=symbol).first()


def _refresh():
    from bot_program import etoro_quotes
    return etoro_quotes.refresh()


# ── the beats ─────────────────────────────────────────────────────────────

class TheBeatsTests(SimpleTestCase):

    def test_the_quotes_beat_every_30_s_on_the_fast_queue(self):
        from config.celery import app
        entry = _beat("refresh-etoro-quotes")
        self.assertEqual(entry["task"],
                         "bot_program.tasks.refresh_etoro_quotes")
        self.assertEqual(entry["schedule"], 30.0)
        # a run not started within the beat is dropped, never queued
        # behind a slow one (expire_seconds: the database scheduler's
        # spelling, django_celery_beat ModelEntry._unpack_options)
        self.assertEqual(entry["options"],
                         {"expires": 25, "expire_seconds": 25})
        self.assertEqual(
            app.conf.task_routes["bot_program.tasks.refresh_etoro_quotes"],
            {"queue": "fast"})

    def test_the_sync_every_60_s(self):
        self.assertEqual(_beat("sync-etoro-accounts")["schedule"], 60.0)

    def test_the_reconcile_stays_every_5_minutes_the_ticks_row_its(self):
        """The bots' component row (pipeline_asset_bots) is judged
        against its most frequent writer (core.component_digest
        .beat_periods): the 300 s tick, which a */2 reconcile would
        displace."""
        from core.component_digest import beat_periods
        from core.day_of_sauron import schedule_words
        rec = _beat("reconcile-asset-bot-trades")["schedule"]
        self.assertEqual(rec, crontab(minute="*/5"))
        self.assertEqual(schedule_words(rec)[:3],
                         ("every 5 min", 300.0, "cron"))
        self.assertAlmostEqual(beat_periods()["pipeline_asset_bots"],
                               _beat("tick-asset-bots")["schedule"] / 3600)

    def test_the_forex_poll_every_300_s_the_polite_floor(self):
        """Not 60 s: fetch_forex_quotes asks Yahoo one pair at a time
        (TheForexPollIsOnePairAtATimeTests). 300 s is the floor
        test_data_quality pins ("the forex floor is about being a polite
        yfinance citizen"), still inside the paper trader's 900 s."""
        from bot_program.engine.paper_trader import PaperTrader
        forex = _beat("fetch-forex-live")["schedule"]
        self.assertEqual(forex, 300.0)
        self.assertEqual(forex, _beat("fetch-commodity-live")["schedule"])
        self.assertEqual(forex, _beat("fetch-index-live")["schedule"])
        self.assertLessEqual(forex, PaperTrader.MAX_QUOTE_AGE_SECONDS)

    def test_the_tick_keeps_its_300_s(self):
        self.assertEqual(_beat("tick-asset-bots")["schedule"], 300.0)

    def test_day_places_the_quotes_beat_and_says_its_cadence(self):
        from core import day_of_sauron as day
        scheme = day.day_scheme()
        self.assertEqual(day.STAGE_OF["refresh-etoro-quotes"][0], "see")
        self.assertNotIn("/", day.STAGE_OF["refresh-etoro-quotes"][1])
        found = [t for s in scheme["stages"] for t in s["tasks"]
                 if t["key"] == "refresh-etoro-quotes"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["when"], "30 s")
        self.assertEqual(scheme["unplaced"], [])


class TheSchedulerKeepsTheBeatsTests(TestCase):
    """django_celery_beat's DatabaseScheduler stores each as it is."""

    def test_the_database_scheduler_keeps_them(self):
        from django_celery_beat.schedulers import ModelEntry
        for key, every in (("refresh-etoro-quotes", 30),
                           ("sync-etoro-accounts", 60),
                           ("fetch-forex-live", 300)):
            model, field = ModelEntry.to_model_schedule(
                _beat(key)["schedule"])
            self.assertEqual(field, "interval", key)
            self.assertEqual((model.every, model.period),
                             (every, "seconds"), key)
        model, field = ModelEntry.to_model_schedule(
            _beat("reconcile-asset-bot-trades")["schedule"])
        self.assertEqual(field, "crontab")
        self.assertEqual(model.minute, "*/5")


class TheForexPollIsOnePairAtATimeTests(TestCase):
    """Why the forex poll is not 60 s: it is no batched call. Each pair is
    its own yfinance Ticker, so a pass over N pairs is N lookups (in
    yfinance 1.7.0 three Yahoo requests each for .info, a fourth for the
    one-minute history when .info carries no price)."""

    def test_one_ticker_per_pair(self):
        fake = mock.MagicMock()
        fake.Ticker.return_value.info = {"regularMarketPrice": 1.1,
                                         "regularMarketChangePercent": 0.1}
        pairs = [_instrument(s, "forex")
                 for s in ("EURUSD", "GBPUSD", "USDJPY")]
        with mock.patch("market_data.adapters.alpha_vantage.API_KEY", ""), \
                mock.patch("core.market_calendar.is_forex_open",
                           return_value=True), \
                mock.patch.dict("sys.modules", {"yfinance": fake}), \
                mock.patch("market_data.tasks._quote_universe",
                           return_value=pairs):
            from market_data.tasks import fetch_forex_quotes
            out = fetch_forex_quotes.__wrapped__.__wrapped__()
        self.assertEqual(out["attempted"], 3)
        self.assertEqual(sorted(c.args[0] for c in fake.Ticker.call_args_list),
                         ["EURUSD=X", "GBPUSD=X", "USDJPY=X"])


# ── eToro's own quotes ────────────────────────────────────────────────────

class _QuotesCase(TestCase):
    """A live eToro account keyed with the suite's user key, the switches
    on, the platform's instruments AAA..EEE (ids 11..55) and the real
    adapter over a fake wire answering each id at its price."""

    PRICES = {11: 10.0, 22: 20.0, 33: 30.0, 44: 40.0, 55: 50.0}

    def setUp(self):
        super().setUp()
        cache.clear()
        vh.reset()
        eb.forget_all()
        er.forget_all()
        self.addCleanup(cache.clear)
        self.addCleanup(vh.reset)
        self.addCleanup(eb.forget_all)
        self.addCleanup(er.forget_all)
        _components()
        self.user = User.objects.create_user("fr_quotes", password="x")
        self.acct = _account(self.user)
        self.cfg = _cfg(self.user, "live", ["AAA", "BBB"])
        for s in IDS:
            _instrument(s, "stock")
        self.wire = _Wire(dict(self.PRICES))
        self.client = _trader(self.wire)
        p = mock.patch(CLIENT_SEAM, return_value=self.client)
        p.start()
        self.addCleanup(p.stop)
        # a 5xx's one bounded retry, without its 0.8 s sleep
        p = mock.patch.object(ec, "READ_RETRY_DELAY_S", 0.0)
        p.start()
        self.addCleanup(p.stop)


class TheQuotesAreWrittenTests(_QuotesCase):

    def test_etoros_bid_ask_and_last_for_each_open_real_row(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        out = _refresh()
        self.assertEqual(sorted(self.wire.rates()), ["11", "22"])
        for symbol, last in (("AAA", "10.0"), ("BBB", "20.0")):
            q = _quote(symbol)
            self.assertEqual(q.source, "etoro", symbol)
            self.assertEqual(q.last, Decimal(last), symbol)
            self.assertEqual(q.bid, Decimal(last) - Decimal("0.1"), symbol)
            self.assertEqual(q.ask, Decimal(last) + Decimal("0.1"), symbol)
        self.assertEqual(out["written"], 2)

    def test_one_read_for_two_rows_of_one_instrument(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "AAA")
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])

    def test_only_the_open_real_etoro_rows_are_read(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB", paper=True)                  # the simulator
        demo = _held(self.cfg, "CCC")                       # eToro's demo
        demo.metadata = dict(demo.metadata, broker_env="paper")
        demo.save(update_fields=["metadata"])
        other = _held(self.cfg, "DDD")                      # another venue
        other.metadata = dict(other.metadata, broker="saxo")
        other.save(update_fields=["metadata"])
        _held(self.cfg, "EEE", status="CLOSED")
        working = _held(self.cfg, "BBB")                    # an order
        working.metadata = dict(working.metadata, entry_working=True)
        working.save(update_fields=["metadata"])
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])
        for symbol in ("BBB", "CCC", "DDD", "EEE"):
            self.assertIsNone(_quote(symbol), symbol)

    def test_a_close_pending_row_is_still_open_at_etoro(self):
        _held(self.cfg, "AAA", status="CLOSE_PENDING")
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])

    def test_a_demo_account_reads_nothing(self):
        type(self.acct).objects.filter(pk=self.acct.pk).update(demo=True)
        _held(self.cfg, "AAA")
        _refresh()
        self.assertEqual(self.wire.rates(), [])

    def test_no_open_row_no_request(self):
        out = _refresh()
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(out["written"], 0)

    def test_a_zero_answer_writes_nothing(self):
        """eToro's "0" (a shut market's answer) is no price: write_quote
        refuses it, and the platform's quote stays what it was."""
        self.wire.prices[11] = 0
        _held(self.cfg, "AAA")
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])
        self.assertIsNone(_quote("AAA"))

    def test_a_side_eToro_did_not_print_is_none_never_zero(self):
        """A row with a last execution and no bid or ask: a zero bid would
        value an open long at nothing (portfolio's closing side)."""
        self.wire.body = lambda ids: {"rates": [
            {"instrumentId": i, "bid": 0, "ask": 0, "lastExecution": 10.5}
            for i in ids]}
        _held(self.cfg, "AAA")
        _refresh()
        q = _quote("AAA")
        self.assertEqual(q.last, Decimal("10.5"))
        self.assertIsNone(q.bid)
        self.assertIsNone(q.ask)

    def test_an_instrument_whose_quote_is_another_instrument_is_not_read(self):
        """XAUUSD's platform quote is Yahoo's GC=F, the gold FUTURE: eToro's
        spot written over it would put the basis into every paper mark of
        the symbol (paper_exits: "a basis, not a crossing"). The row's own
        P&L reads eToro's figure from the sync."""
        from market_data.quotes import write_quote
        gold = _instrument("XAUUSD", "commodity", "COMEX")
        write_quote("XAUUSD", last="2400", source="yfinance",
                    instrument=gold)
        self.client._ids["XAUUSD"] = 18
        _held(self.cfg, "XAUUSD")
        _held(self.cfg, "AAA")
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])
        self.assertEqual(_quote("XAUUSD").source, "yfinance")

    def test_the_task_reads_the_switches_itself_and_writes_no_component_row(
            self):
        """Ungated by guarded_task, as refresh_etoro_cells: the component
        row broker_account_sync is the sync's verdict, and a beat every 30 s
        must not overwrite it."""
        from bot_program import tasks
        from core.component_digest import _component_key_of
        from core.platform_control import PlatformComponent
        self.assertIsNone(_component_key_of(tasks.refresh_etoro_quotes))
        before = PlatformComponent.objects.get(key="broker_account_sync")
        _held(self.cfg, "AAA")
        tasks.refresh_etoro_quotes()
        after = PlatformComponent.objects.get(key="broker_account_sync")
        self.assertEqual((after.last_run_at, after.last_status,
                          after.run_count),
                         (before.last_run_at, before.last_status,
                          before.run_count))
        self.assertEqual(self.wire.rates(), ["11"])

    def test_the_switches(self):
        _held(self.cfg, "AAA")
        for off in ("broker_account_sync", "platform_master"):
            _components(**{off: False})
            out = _refresh()
            self.assertEqual(self.wire.calls, [], off)
            self.assertIn("off", out["skipped"], off)
        _components()
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])

    def test_one_pass_at_a_time(self):
        from bot_program import etoro_quotes
        _held(self.cfg, "AAA")
        cache.add(etoro_quotes.LOCK_KEY, 1, 60)
        out = _refresh()
        self.assertEqual(self.wire.calls, [])
        self.assertIn("running", out["skipped"])
        cache.delete(etoro_quotes.LOCK_KEY)
        _refresh()
        self.assertEqual(self.wire.rates(), ["11"])
        self.assertIsNone(cache.get(etoro_quotes.LOCK_KEY),
                          "the pass gives its lock back")


class TheEtoroQuoteOutranksYfinanceTests(_QuotesCase):

    def test_held_while_fresh_then_yfinance_writes_again(self):
        from market_data.quotes import PRIORITY_HOLD_SECONDS, write_quote
        _held(self.cfg, "AAA")
        _refresh()
        self.assertFalse(write_quote("AAA", last="9.5", source="yfinance"))
        self.assertEqual(_quote("AAA").source, "etoro")
        later = timezone.now() + timedelta(seconds=PRIORITY_HOLD_SECONDS + 1)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.assertTrue(write_quote("AAA", last="9.5",
                                        source="yfinance"))
        q = _quote("AAA")
        self.assertEqual(q.source, "yfinance")
        self.assertIsNone(q.bid, "a write without sides clears them")

    def test_the_forex_poll_does_not_ask_yahoo_for_a_pair_etoro_holds(self):
        fake = mock.MagicMock()
        fake.Ticker.return_value.info = {"regularMarketPrice": 1.1}
        eurusd = _instrument("EURUSD", "forex")
        _instrument("GBPUSD", "forex")
        self.client._ids["EURUSD"] = 1
        self.wire.prices[1] = 1.0852
        fx = _cfg(self.user, "fx", ["EURUSD"], asset_class="forex")
        _held(fx, "EURUSD")
        _refresh()
        self.assertEqual(_quote("EURUSD").source, "etoro")
        with mock.patch("market_data.adapters.alpha_vantage.API_KEY", ""), \
                mock.patch("core.market_calendar.is_forex_open",
                           return_value=True), \
                mock.patch.dict("sys.modules", {"yfinance": fake}), \
                mock.patch("market_data.tasks._quote_universe",
                           return_value=[eurusd]):
            from market_data.tasks import fetch_forex_quotes
            out = fetch_forex_quotes.__wrapped__.__wrapped__()
        fake.Ticker.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(_quote("EURUSD").source, "etoro")


class TheBatchTests(_QuotesCase):
    """The batched read (E2) carries every instrument in one request once
    the operator's measurement proved it; until then, one read each."""

    def setUp(self):
        super().setUp()
        for name, value in (("CACHE", True), ("MEASURED_FIRST", True)):
            p = mock.patch.object(er, name, value)
            p.start()
            self.addCleanup(p.stop)
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")

    def test_one_read_each_while_the_batch_waits_for_its_measurement(self):
        _refresh()
        self.assertEqual(sorted(self.wire.rates()), ["11", "22"])
        self.assertEqual(_quote("BBB").last, Decimal("20.0"))

    def test_one_batched_read_once_proven(self):
        self.assertTrue(er.prove("demo", "keys ['rates']"))
        _refresh()
        self.assertEqual(self.wire.sets(), ["11,22"])
        self.assertEqual(_quote("AAA").last, Decimal("10.0"))
        self.assertEqual(_quote("BBB").bid, Decimal("19.9"))

    def test_a_row_the_batch_left_out_is_read_alone(self):
        er.prove("demo", "keys ['rates']")
        self.wire.alone_only = {22}
        _refresh()
        self.assertEqual(self.wire.rates(), ["11,22", "22"])
        self.assertEqual(_quote("BBB").last, Decimal("20.0"))

    def test_a_failed_batch_ends_the_pass(self):
        er.prove("demo", "keys ['rates']")
        self.wire.status = [503]
        out = _refresh()
        # the batch and its one bounded retry, nothing read alone after it
        self.assertEqual(self.wire.rates(), ["11,22", "11,22"])
        self.assertIsNone(_quote("AAA"))
        self.assertIn("stopped", out)

    def test_an_answer_read_in_the_last_15_s_is_not_asked_again(self):
        """The shared rates cache (E2) answered by another reader (the
        manage tick, the CLOSE button) within PREFETCH_FRESH_S."""
        self.client.ticker("AAA")
        before = len(self.wire.rates())
        _refresh()
        self.assertEqual(self.wire.rates()[before:], ["22"])


class TheCapTests(_QuotesCase):

    def test_at_most_the_cap_a_pass_stalest_first(self):
        from bot_program import etoro_quotes
        cap = etoro_quotes.SINGLE_READS_PER_PASS
        self.assertEqual(cap, 6)
        ids = {f"S{i}": 100 + i for i in range(1, 9)}
        for s, i in ids.items():
            _instrument(s, "stock")
            self.client._ids[s] = i
            self.wire.prices[i] = float(i)
            _held(self.cfg, s)
        clock = _Clock(1_000_000.0)
        with mock.patch.object(etoro_quotes, "_now", clock):
            _refresh()
            first = list(self.wire.rates())
            clock.t += 30
            _refresh()
            second = self.wire.rates()[len(first):]
        self.assertEqual(first, [str(100 + i) for i in range(1, 7)])
        self.assertEqual(len(second), cap)
        self.assertEqual(second[:2], ["107", "108"],
                         "the instruments the last pass did not reach first")


class TheBudgetTests(_QuotesCase):
    """At P3, the marks' priority in the budget (E1), never P1: a pass the
    budget refuses sends nothing and is no venue failure."""

    def setUp(self):
        super().setUp()
        for target, name in ((eb, "BUDGET"), (ec, "RATE_PAUSE")):
            p = mock.patch.object(target, name, True)
            p.start()
            self.addCleanup(p.stop)
        self.bclock = _Clock(600_000.0)
        p = mock.patch.object(eb, "_now", self.bclock)
        p.start()
        self.addCleanup(p.stop)

    def _fill(self, n):
        for _ in range(int(n)):
            eb.spend(KH, eb.MARKET, eb.P1, where="ticker")
        eb.flush()

    def test_every_read_is_taken_at_p3(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        _refresh()
        eb.flush()
        win = eb.window()
        self.assertEqual(cache.get(eb._p_key(KH, eb.MARKET, win, eb.P3)), 2)
        self.assertIsNone(cache.get(eb._p_key(KH, eb.MARKET, win, eb.P1)))

    def test_a_row_etoro_holds_no_stop_for_is_still_p3_here(self):
        """Its own P1 mark is the manage tick's; this beat only shows."""
        _held(self.cfg, "AAA", protected=False)
        self._fill(eb.limit(eb.MARKET, eb.P3))
        out = _refresh()
        self.assertEqual(self.wire.calls, [])
        self.assertIn("eToro budget", out["stopped"])

    def test_a_refusal_ends_the_pass_and_is_no_failure(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self._fill(eb.limit(eb.MARKET, eb.P3) - 1)
        out = _refresh()
        self.assertEqual(len(self.wire.rates()), 1, "one token, one read")
        self.assertIn("eToro budget", out["stopped"])
        self.assertEqual(out["written"], 1)
        self.assertEqual(vh._load(vh._key("etoro", "live")), {},
                         "a refusal is never a venue failure")

    def test_a_429_ends_the_pass_and_the_pause_skips_the_next(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self.wire.status = [429]
        out = _refresh()
        self.assertEqual(self.wire.rates(), ["11"], "never retried")
        self.assertIn("stopped", out)
        self.assertGreater(eb.pause_left(KH, "live"), 0)
        self.wire.status = [200]
        out = _refresh()
        self.assertEqual(self.wire.rates(), ["11"])
        self.assertIn("pause", out["skipped"])

    def test_a_5xx_is_the_reads_one_retry_and_ends_the_pass(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self.wire.status = [503]
        out = _refresh()
        self.assertEqual(self.wire.rates(), ["11", "11"])
        self.assertIn("stopped", out)

    def test_the_batch_and_the_rows_it_left_out_are_p3_too(self):
        """2026-11-06, the feed spec's P-c.3: the batch, once proven, and
        the single read of a row it left out are taken at P3, never P1."""
        for name, value in (("CACHE", True), ("MEASURED_FIRST", True)):
            p = mock.patch.object(er, name, value)
            p.start()
            self.addCleanup(p.stop)
        er.prove("demo", "keys ['rates']")
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self.wire.alone_only = {22}
        _refresh()
        eb.flush()
        win = eb.window()
        self.assertEqual(self.wire.rates(), ["11,22", "22"])
        self.assertEqual(cache.get(eb._p_key(KH, eb.MARKET, win, eb.P3)), 2)
        self.assertIsNone(cache.get(eb._p_key(KH, eb.MARKET, win, eb.P1)))

    def test_never_while_etoro_is_sick(self):
        _held(self.cfg, "AAA")
        for _ in range(vh.SICK_BURST):
            vh.note("etoro", "live", "ticker", code=500)
        self.assertIsNotNone(vh.sick("etoro", "live"))
        out = _refresh()
        self.assertEqual(self.wire.calls, [])
        self.assertIn("sick", out["skipped"])


class TheShutMarketTests(_ShutOn, TestCase):
    """A market the shut cadence (E2) holds shut is not asked: its price
    does not move, and a quote rewritten every 30 s would read fresh."""

    def test_a_shut_commodity_is_not_asked_an_open_one_is(self):
        _components()
        user = User.objects.create_user("fr_shut", password="x")
        _account(user)
        cfg = _cfg(user, "W")
        _instrument("AAA", "commodity", "COMEX")
        _instrument("BBB", "crypto")
        _held(cfg, "AAA")
        _held(cfg, "BBB", asset_class="crypto")
        w = _Wire({11: 101.0, 22: 102.0})
        with self._at(SAT), mock.patch(CLIENT_SEAM, return_value=_trader(w)):
            _refresh()
        self.assertEqual(w.rates(), ["22"])


# ── the feed spec's asks to this beat (2026-11-06, P-c) ──────────────────

class TheRefusedWritesTests(_QuotesCase):
    """THE FEED SPEC'S P-c.1: where a higher-ranked feed holds the row (a
    stream, OANDA's, Binance's or Finnhub's, or IBKR's), write_quote's
    precedence refuses eToro's write for PRIORITY_HOLD_SECONDS after each
    of its ticks (should_write False), and the beat did nothing there,
    silently. Each such refusal is now counted, the feed that held the row
    named, the last pass and today's counts kept, and manage.py
    etoro_budget says them."""

    def _stream_holds(self, symbol, source="oanda_stream"):
        from market_data.quotes import write_quote
        self.assertTrue(write_quote(symbol, last="9.99", source=source))

    def test_a_write_a_stream_holds_is_counted_and_its_feed_named(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self._stream_holds("AAA")
        with self.assertLogs("bot_program.etoro_quotes", level="INFO") as said:
            out = _refresh()
        self.assertEqual(sorted(self.wire.rates()), ["11", "22"])
        self.assertEqual((out["written"], out["refused"]), (1, 1))
        self.assertEqual(out["held_by"], {"AAA": "oanda_stream"})
        self.assertEqual(_quote("AAA").source, "oanda_stream",
                         "the stream keeps its row")
        self.assertEqual(_quote("BBB").source, "etoro")
        self.assertTrue(any("1 write refused" in line
                            and "AAA: oanda_stream" in line
                            for line in said.output), said.output)

    def test_a_zero_answer_is_no_refusal(self):
        """eToro's "0" is no price: write_quote refuses it for that, not
        for precedence, and it is counted as neither."""
        self.wire.prices[11] = 0
        _held(self.cfg, "AAA")
        self._stream_holds("AAA")
        out = _refresh()
        self.assertEqual((out["written"], out["refused"]), (0, 0))
        self.assertNotIn("held_by", out)

    def test_once_the_hold_ends_the_write_goes(self):
        from market_data.quotes import PRIORITY_HOLD_SECONDS
        _held(self.cfg, "AAA")
        self._stream_holds("AAA")
        later = timezone.now() + timedelta(seconds=PRIORITY_HOLD_SECONDS + 1)
        with mock.patch("django.utils.timezone.now", return_value=later):
            out = _refresh()
        self.assertEqual((out["written"], out["refused"]), (1, 0))
        self.assertEqual(_quote("AAA").source, "etoro")

    def test_the_last_pass_and_todays_counts_are_kept(self):
        from bot_program import etoro_quotes
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self._stream_holds("AAA")
        clock = _Clock(1_800_000_000.0)
        with mock.patch.object(etoro_quotes, "_now", clock):
            _refresh()
            clock.t += 30
            _refresh()
            kept = etoro_quotes.report()
        last = kept["last"]
        self.assertEqual((last["asked"], last["written"], last["refused"]),
                         (2, 1, 1))
        self.assertEqual(last["held_by"], {"AAA": "oanda_stream"})
        self.assertEqual(last["at"], clock.t)
        today = kept["today"]
        self.assertEqual((today["asked"], today["written"],
                          today["refused"]), (4, 2, 2))
        self.assertEqual(today["held_by"], {"AAA": "oanda_stream"})

    def test_the_budget_command_says_them(self):
        _held(self.cfg, "AAA")
        _held(self.cfg, "BBB")
        self._stream_holds("AAA")
        _refresh()
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        text = out.getvalue()
        self.assertIn("eToro's own quotes (every 30 s): the last pass at",
                      text)
        self.assertIn("2 asked, 1 written, 1 refused: a higher-ranked feed "
                      "holds the row (AAA: oanda_stream)", text)
        self.assertIn("today (UTC): 2 asked, 1 written, 1 refused for a "
                      "higher-ranked feed (AAA: oanda_stream)", text)

    def test_a_skipped_pass_and_no_pass_are_said(self):
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        self.assertIn("eToro's own quotes (every 30 s): no pass recorded in "
                      "the last two days", out.getvalue())
        _refresh()
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        self.assertIn("skipped: no open real eToro row", out.getvalue())


class ThePushedTickSaysItsSourceTests(TestCase):
    """THE FEED SPEC'S P-c.2 (its harm 24): push_quote_update carried no
    source, so after every pushed tick the headband card's source read
    "—", and a row's switch back from eToro's quote to Yahoo's once the
    position closed (the beat stops, the 300 s hold ends) showed on no
    pushed tick. Each pushed tick now says its source; the browser already
    paints a tick's `source` (templates/base.html, dhSync)."""

    def test_the_pushed_tick_carries_its_source(self):
        from dashboard import consumers
        sent = []

        class _Layer:
            async def group_send(self, group, message):
                sent.append((group, message))
        with mock.patch("channels.layers.get_channel_layer",
                        return_value=_Layer()):
            consumers.push_quote_update("AAPL", Decimal("191.0"),
                                        Decimal("0.5"), source="yfinance")
            consumers.push_quote_update("AAPL", Decimal("191.0"),
                                        Decimal("0.5"))
        self.assertEqual(sent[0], ("dashboard_live", {
            "type": "quote_update",
            "data": {"symbol": "AAPL", "price": "191.0",
                     "change_pct": "0.5", "source": "yfinance"}}))
        self.assertEqual(sent[1][1]["data"],
                         {"symbol": "AAPL", "price": "191.0",
                          "change_pct": "0.5"},
                         "a caller that names none pushes what it pushed")

    def test_the_switch_back_from_etoro_is_labelled_on_the_pushed_tick(self):
        from market_data.quotes import PRIORITY_HOLD_SECONDS, write_quote
        from market_data.tasks import fetch_live_quotes
        aapl = _instrument("AAPL", "stock")
        self.assertTrue(write_quote("AAPL", last="190.5", source="etoro",
                                    bid="190.4", ask="190.6",
                                    instrument=aapl))
        pushed = []
        fn = fetch_live_quotes
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        with mock.patch("core.market_calendar.is_us_market_open",
                        return_value=True), \
                mock.patch("signals.universe.quote_targets",
                           return_value=[aapl]), \
                mock.patch("market_data.adapters.yfinance_adapter"
                           ".fetch_quote",
                           return_value={"last": 191.0, "change_pct": 0.5,
                                         "volume": 100}), \
                mock.patch("dashboard.consumers.push_quote_update",
                           side_effect=lambda *a, **k: pushed.append(k)):
            fn(None)
            self.assertEqual(pushed, [], "eToro's quote holds the row")
            later = timezone.now() + timedelta(
                seconds=PRIORITY_HOLD_SECONDS + 1)
            with mock.patch("django.utils.timezone.now",
                            return_value=later):
                fn(None)
        self.assertEqual(pushed, [{"source": "yfinance"}])
        self.assertEqual(_quote("AAPL").source, "yfinance")

    def test_the_browser_paints_the_source_of_a_quote_message(self):
        base = (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")
        self.assertIn("if (msg.type === 'quote_stream' || msg.type === "
                      "'quote') applyTick(msg.data);", base)
        self.assertIn("put('src', d.source || '');", base)


class TheTwelveAMinuteTests(_QuotesCase):
    """THE FEED SPEC'S P-c.3: the beat's reads stay at P3 (TheBudgetTests)
    and inside its twelve a minute, SINGLE_READS_PER_PASS at the 30 s beat,
    the room the feed's budget leaves it. Verified: a proven batch that
    left rows out was followed by six single reads (seven requests a
    pass), and a run started late (up to its 25 s expiry) beside the next
    beat's run put three passes in a minute. A pass now sends at most six
    requests in all, and a key no more than twelve in any rolling
    minute."""

    def _instruments(self, n):
        ids = {f"S{i}": 100 + i for i in range(1, n + 1)}
        for s, i in ids.items():
            _instrument(s, "stock")
            self.client._ids[s] = i
            self.wire.prices[i] = float(i)
            _held(self.cfg, s)
        return ids

    def test_twelve_a_minute_at_the_beat(self):
        from bot_program import etoro_quotes
        self.assertEqual(etoro_quotes.READS_PER_MINUTE, 12)
        self.assertEqual(etoro_quotes.READS_PER_MINUTE,
                         etoro_quotes.SINGLE_READS_PER_PASS * 60
                         // etoro_quotes.BEAT_S)
        self.assertEqual(_beat("refresh-etoro-quotes")["schedule"],
                         etoro_quotes.BEAT_S)

    def test_three_passes_in_a_minute_never_send_more_than_twelve(self):
        from bot_program import etoro_quotes
        self._instruments(8)
        clock = _Clock(1_000_000.0)
        sent = []
        with mock.patch.object(etoro_quotes, "_now", clock):
            for step in (0, 25, 5, 31):
                clock.t += step
                before = len(self.wire.rates())
                out = _refresh()
                sent.append(len(self.wire.rates()) - before)
                if step == 5:
                    third = out
        self.assertEqual(sent, [6, 6, 0, 6])
        self.assertIn("12 reads a minute", third["stopped"])

    def test_a_batch_and_its_single_reads_are_six_a_pass_at_most(self):
        """A proven batch that left rows out: the batch is one of the six,
        the rows it left out are read alone with the five left."""
        from bot_program import etoro_quotes
        for name, value in (("CACHE", True), ("MEASURED_FIRST", True)):
            p = mock.patch.object(er, name, value)
            p.start()
            self.addCleanup(p.stop)
        er.prove("demo", "keys ['rates']")
        ids = self._instruments(8)
        self.wire.alone_only = set(ids.values()) - {101}
        out = _refresh()
        sent = self.wire.rates()
        self.assertEqual(len(sent), etoro_quotes.SINGLE_READS_PER_PASS)
        self.assertEqual(len(sent[0].split(",")), 8,
                         "one batch carried the eight")
        self.assertEqual(out["written"], 6, "the batched row, five alone")


# ── the sync every minute ─────────────────────────────────────────────────

class TheSyncEveryMinuteTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("fr_sync", password="x")
        self.acct = _account(self.user)

    def _sync(self, at):
        from tests.test_sync_walks_etoro import _client, _sync_etoro
        with mock.patch("django.utils.timezone.now", return_value=at):
            return _sync_etoro(_client())

    def test_the_cells_every_pass_the_history_every_five_minutes(self):
        from bot_program.equity_models import BrokerEquityReading
        from bot_program.models import EtoroAccount
        t0 = timezone.now().replace(microsecond=0)

        def rows():
            return BrokerEquityReading.objects.filter(
                broker="etoro", account_pk=self.acct.pk).count()
        self._sync(t0)
        self.assertEqual(rows(), 1)
        for minute in (1, 2, 3, 4):
            out = self._sync(t0 + timedelta(minutes=minute))
            self.assertEqual(out["stored"], 1)
            self.assertEqual(
                EtoroAccount.objects.get(pk=self.acct.pk).last_equity_at,
                t0 + timedelta(minutes=minute))
            self.assertEqual(rows(), 1, minute)
        self._sync(t0 + timedelta(minutes=5))
        self.assertEqual(rows(), 2)

    def test_the_etoro_stall_alert_waits_fifteen_misses(self):
        from bot_program.models import IBKRAccount
        from bot_program.tasks import _note_broker_miss
        ib = IBKRAccount.objects.create(user=self.user, port=4003,
                                        label="IB")
        ib.set_credentials("U1")
        ib.save()
        with mock.patch("bot_program.notifications."
                        "notify_broker_unreachable") as said, \
                self.assertLogs("bot_program.tasks", level="WARNING"):
            for _ in range(14):
                _note_broker_miss(self.acct, self.user)
            self.assertFalse(said.called, "fourteen minutes is a blip")
            _note_broker_miss(self.acct, self.user)
            self.assertEqual(said.call_count, 1)
            for _ in range(3):
                _note_broker_miss(ib, self.user)
            self.assertEqual(said.call_count, 2, "IBKR still says it at 3")

    def test_fifteen_passes_of_the_beat_are_the_fifteen_minutes(self):
        from bot_program.tasks import (BROKER_MISS_ALERT_AFTER,
                                       broker_miss_alert_after)
        self.assertEqual(broker_miss_alert_after("etoro")
                         * _beat("sync-etoro-accounts")["schedule"], 900)
        self.assertEqual(broker_miss_alert_after("ibkr"),
                         BROKER_MISS_ALERT_AFTER)
        self.assertEqual(broker_miss_alert_after("saxo"),
                         BROKER_MISS_ALERT_AFTER)

    def test_the_alarm_reads_the_same_count(self):
        from bot_program import alarm
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="broker_account_sync",
            defaults={"name": "s", "category": "system", "is_enabled": True})
        key = f"broker_sync:miss:etoro:{self.acct.pk}"
        cache.set(key, 14, 3600)
        self.assertEqual(alarm.read_brokers(timezone.now()), [])
        cache.set(key, 15, 3600)
        said = alarm.read_brokers(timezone.now())
        self.assertEqual(len(said), 1)
        self.assertIn(f"eToro account #{self.acct.pk} has not answered 15 "
                      f"syncs in a row", said[0].words)


# ── the words ────────────────────────────────────────────────────────────

class TheWordsTests(SimpleTestCase):

    def _read(self, *parts):
        return (Path(settings.BASE_DIR).joinpath(*parts)
                .read_text(encoding="utf-8"))

    def test_the_switch_names_the_minute_and_the_quotes(self):
        from core.platform_control import DEFAULT_COMPONENTS
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "broker_account_sync")
        self.assertIn("eToro every minute", row["description"])
        self.assertIn("eToro's own quotes for the open real positions "
                      "every 30 s", row["description"])
        forex = next(c for c in DEFAULT_COMPONENTS
                     if c["key"] == "scraper_forex")
        self.assertIn("(every 5 min)", forex["description"])

    def test_the_broker_card_says_the_minute(self):
        card = self._read("templates", "_partials", "broker_account.html")
        self.assertIn("eToro every minute", card)
        self.assertNotIn("eToro every 5 min", card)

    def test_the_book_and_the_wall_keep_the_reconciles_five_minutes(self):
        from core import book_content as book
        text = " ".join(str(c) for c in book.CHAPTERS)
        self.assertIn("Every 5 minutes, around the clock", text)
        wall = self._read("templates", "landing", "the_wall.html")
        self.assertIn("every 5 min, around the clock", wall)
