"""THE CANDLE HEADROOM COMMAND (market_data/candle_headroom.py,
market_data/management/commands/etoro_candle_headroom.py; spec §5.2a item
3, O1): before the Orcs' 15m and 5m candles may run, the operator measures
how fast eToro answers candle reads before its first 429. A dry run by
default (it prints the plan and sends nothing); `--yes` runs the ramp,
refused on a live account without `--live`, while eToro is sick, after a
recent trading-lane 429 or while a bar pass holds its lock; the ramp stops
at its first 429 or its request ceiling and records the clean rate and the
tape's budget per pass. Its reads are background reads.

Run with:  python manage.py test tests.test_etoro_candle_headroom
"""
import io
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from bot_program.engine.etoro_client import EtoroTrader
from tests.test_bars_etoro_quota import H, _Resp, _Wire

MIN = 60_000


class _RampWire(_Wire):
    """Answers candles until `budget` candle reads, then 429s."""
    ENUM = {**_Wire.ENUM, "FifteenMinutes": 15 * MIN, "FiveMinutes": 5 * MIN,
            "OneHour": H}

    def __init__(self, ids, budget=10_000, **kw):
        super().__init__(ids, **kw)
        self.budget = budget

    def get(self, url, **kw):
        if "/history/candles" in url and len(self.candle_calls()) >= \
                self.budget:
            self.calls.append(url)
            return _Resp(429, headers={"x-ratelimit-remaining": "0"})
        return super().get(url, **kw)


class _Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def mono(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class _Headroom(TestCase):

    def setUp(self):
        from django.core.cache import cache

        from bot_program import venue_health
        from bot_program.engine import etoro_client as ec
        from instruments.models import Instrument
        cache.clear()
        venue_health.reset()
        self.addCleanup(venue_health.reset)
        self.addCleanup(cache.clear)
        for memo in (ec._SEARCH_IDS, ec._SEARCH_NO, ec._RATE_PAUSE):
            memo.clear()
            self.addCleanup(memo.clear)
        for s in ("EURUSD", "GBPUSD"):
            Instrument.objects.get_or_create(
                symbol=s, defaults={"name": s, "asset_class": "forex"})
        self.wire = _RampWire({"EURUSD": 1000, "GBPUSD": 1001})
        self.clock = _Clock()
        self.env = "demo"

    def _client(self, *_a, **_k):
        t = EtoroTrader("k", "u", env=self.env)
        t._session = self.wire
        return t

    def run_cmd(self, *args):
        out = io.StringIO()
        with patch("market_data.candle_headroom.client_for",
                   side_effect=self._client), \
                patch("market_data.candle_headroom._mono", self.clock.mono), \
                patch("market_data.candle_headroom._sleep", self.clock.sleep):
            call_command("etoro_candle_headroom", "--symbol", "EURUSD",
                         "--symbol", "GBPUSD", *args, stdout=out)
        return out.getvalue()

    def recorded(self):
        from bot_program.orcs.models import OrcSetting
        return OrcSetting.get("etoro_candle_headroom")


class TheDryRunTests(_Headroom):

    def test_a_dry_run_sends_nothing_and_records_nothing(self):
        out = self.run_cmd()
        self.assertIn("A dry run: nothing was sent.", out)
        self.assertIn("demo", out)
        self.assertIn("EURUSD, GBPUSD", out)
        self.assertIn("at most 60 candle reads", out)
        self.assertEqual(self.wire.calls, [])
        self.assertIsNone(self.recorded())

    def test_the_ramp_halves_its_gap_every_ten_reads(self):
        from market_data.candle_headroom import ramp
        gaps = ramp(40)
        self.assertEqual(gaps[:10], [2.0] * 10)
        self.assertEqual(gaps[10:20], [1.0] * 10)
        self.assertEqual(gaps[20:30], [0.5] * 10)
        self.assertEqual(gaps[30:], [0.25] * 10)
        self.assertEqual(min(ramp(200)), 0.25)


class TheGuardsTests(_Headroom):

    def test_a_live_account_needs_live(self):
        self.env = "live"
        with self.assertRaises(CommandError) as cm:
            self.run_cmd("--yes")
        self.assertIn("--live", str(cm.exception))
        self.assertEqual(self.wire.calls, [])

    def test_refused_while_sick_or_after_a_recent_429(self):
        from bot_program import venue_health
        with patch.object(venue_health, "sick", return_value=True):
            with self.assertRaises(CommandError) as cm:
                self.run_cmd("--yes")
        self.assertIn("sick", str(cm.exception))
        with patch.object(venue_health, "recent_refusals",
                          return_value=[{"where": "orders"}]):
            with self.assertRaises(CommandError) as cm:
                self.run_cmd("--yes")
        self.assertIn("429", str(cm.exception))
        self.assertEqual(self.wire.calls, [])

    def test_refused_while_a_bar_pass_holds_its_lock(self):
        from django.core.cache import cache

        from market_data.tasks import BARS_LOCK_KEY
        cache.set(BARS_LOCK_KEY, "x", 60)
        with self.assertRaises(CommandError) as cm:
            self.run_cmd("--yes")
        self.assertIn("bar refresh", str(cm.exception))
        self.assertEqual(self.wire.calls, [])


class TheRampTests(_Headroom):

    def test_stops_at_the_first_429_and_records(self):
        self.wire.budget = 12
        out = self.run_cmd("--yes")
        candles = self.wire.candle_calls()
        self.assertEqual(len(candles), 13, "twelve answered, the 13th 429")
        self.assertTrue(all(u.endswith("/2") for u in candles),
                        "two bars a read")
        self.assertTrue(any("/FifteenMinutes/" in u for u in candles))
        self.assertTrue(any("/FiveMinutes/" in u for u in candles))
        rec = self.recorded()
        self.assertEqual(rec["requests"], 12)
        self.assertTrue(rec["hit_429"])
        # twelve clean reads are eleven gaps (nine of 2 s, two of 1 s):
        # 11 reads in 20 s, 33 a minute; never the 36 that counting the
        # first read as a gap would claim (a budget must not run high)
        self.assertAlmostEqual(rec["clean_per_min"], 33.0)
        self.assertAlmostEqual(rec["at_429_per_min"], 60.0)
        self.assertEqual(rec["tape_per_pass"], 57,
                         "floor(0.25 x 33 x 420 / 60)")
        self.assertEqual(rec["world"], "demo")
        self.assertIn("eToro answered HTTP 429", out)

    def test_stops_at_the_ceiling(self):
        self.run_cmd("--yes", "--max-requests", "5")
        self.assertEqual(len(self.wire.candle_calls()), 5)
        rec = self.recorded()
        self.assertFalse(rec["hit_429"])
        self.assertEqual(rec["requests"], 5)

    def test_an_error_that_is_not_a_429_stops_and_records_nothing(self):
        """A read that fails another way (a 404, a 5xx after its retry) is
        no measurement: the command says so and records nothing."""
        wire = self.wire
        real_get = wire.get

        def broken(url, **kw):
            if "/history/candles" in url and len(wire.candle_calls()) >= 2:
                wire.calls.append(url)
                return _Resp(404)
            return real_get(url, **kw)
        wire.get = broken
        with self.assertRaises(CommandError) as cm:
            self.run_cmd("--yes")
        self.assertIn("nothing was recorded", str(cm.exception))
        self.assertIsNone(self.recorded())

    def test_background_reads_never_noted_on_the_venue(self):
        from bot_program import venue_health
        self.wire.budget = 3
        with patch.object(venue_health, "note") as noted:
            self.run_cmd("--yes")
        noted.assert_not_called()
        self.assertFalse(venue_health.sick("etoro", "demo"))


class TheLocksTests(_Headroom):
    """The ramp provokes eToro's 429 on purpose (review, O1c): it never
    runs beside a bar pass or a Mercenary tape pass, holds the tape's lock
    while it runs, ends the moment a bar pass starts (recording nothing),
    and after its 429 every candle pass yields for two minutes instead of
    meeting the same 429 (background 429s never reach the venue's
    health)."""

    def test_refused_while_a_tape_pass_holds_its_lock(self):
        from django.core.cache import cache

        from market_data.tasks import ORC_TAPE_LOCK_KEY
        cache.set(ORC_TAPE_LOCK_KEY, 1, 60)
        with self.assertRaises(CommandError) as cm:
            self.run_cmd("--yes")
        self.assertIn("Mercenary tape pass", str(cm.exception))
        self.assertEqual(self.wire.calls, [])

    def test_holds_the_tape_lock_while_it_reads_and_releases_it(self):
        from django.core.cache import cache

        from market_data.tasks import ORC_TAPE_LOCK_KEY
        wire, real_get, held = self.wire, self.wire.get, []

        def watched(url, **kw):
            if "/history/candles" in url:
                held.append(cache.get(ORC_TAPE_LOCK_KEY))
            return real_get(url, **kw)
        wire.get = watched
        self.run_cmd("--yes", "--max-requests", "4")
        self.assertEqual(held, ["headroom"] * 4)
        self.assertIsNone(cache.get(ORC_TAPE_LOCK_KEY), "released")
        # a tape pass that starts meanwhile stands aside (it cannot add
        # the lock the ramp holds)
        from market_data.tasks import refresh_orc_tape_task
        cache.set(ORC_TAPE_LOCK_KEY, "headroom", 60)
        with patch("core.task_gate.is_component_enabled", return_value=True):
            self.assertIn("idle", refresh_orc_tape_task())

    def test_a_bar_pass_that_starts_ends_the_ramp_and_nothing_is_recorded(
            self):
        from django.core.cache import cache

        from market_data.tasks import BARS_LOCK_KEY
        wire, real_get = self.wire, self.wire.get

        def bar_pass_starts(url, **kw):
            out = real_get(url, **kw)
            if "/history/candles" in url and len(wire.candle_calls()) == 2:
                cache.set(BARS_LOCK_KEY, "pass", 60)
            return out
        wire.get = bar_pass_starts
        with self.assertRaises(CommandError) as cm:
            self.run_cmd("--yes")
        self.assertIn("a bar pass started", str(cm.exception))
        self.assertIn("nothing was recorded", str(cm.exception))
        self.assertEqual(len(wire.candle_calls()), 2,
                         "no read once the bar pass holds its lock")
        self.assertIsNone(self.recorded())

    def test_after_its_429_every_candle_pass_yields_for_two_minutes(self):
        import time

        from django.core.cache import cache

        from market_data.bot_bars import (HEADROOM_429_KEY, _CandlePass,
                                          _etoro_refusing)
        self.assertEqual(_etoro_refusing("demo"), "", "nothing before")
        self.wire.budget = 3
        self.run_cmd("--yes")
        until = float(cache.get(HEADROOM_429_KEY))
        self.assertAlmostEqual(until - time.time(), 120.0, delta=5)
        why = _etoro_refusing("demo")
        self.assertIn("headroom ramp met eToro's HTTP 429", why)
        state = _CandlePass()
        self.assertFalse(state.may_ask("demo"))
        self.assertIn("headroom ramp", state.words())
        cache.set(HEADROOM_429_KEY, time.time() - 1, 60)
        self.assertEqual(_etoro_refusing("demo"), "", "spent")
