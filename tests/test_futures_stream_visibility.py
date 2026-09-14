"""A feed that writes nothing must not look like a quiet market (2026-09-14).

`FundingRate` held 0 rows on the live box. The worker was Up, the socket was
open, `docker logs` had nothing to say, and `funding_carry` refused all 15
crypto instruments for want of the snapshots this streamer is supposed to
write. The subscription-to-nothing case was fixed on 2026-09-13. This is the
other half, and it is the reason that fix could not be confirmed from the
outside: both write paths swallowed every exception into `log.debug`, and
`core.logging_config` puts the root logger at WARNING when DEBUG is off.

So DEBUG is not a volume choice in production. It is a deletion. A write path
that failed on every single tick left no trace anywhere, and an empty table
says nothing at all about whether the feed works — the same "unmeasured is not
zero" that the em dash exists for, one layer down.

The writes were also handed to `asyncio.create_task` with the task dropped on
the floor. An unreferenced task may be garbage-collected before it runs, and
its exception is never retrieved.

WHAT THESE TESTS HOLD

Not the counts themselves — those are the feed's business. They hold that a
failure has a mouth: the first one is a WARNING naming the symbol and the
exception, the heartbeat reports written AND failed for both tables, and the
heartbeat runs on its own task so it still speaks when nothing arrives. A
stream that receives nothing and a stream that writes nothing now read
differently in the log, which is the entire difference between a diagnosis
and a shrug.
"""
import asyncio
import logging
from pathlib import Path
from unittest import mock

from asgiref.sync import async_to_sync
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from market_data.management.commands import stream_binance_futures as fut

SOURCE = (Path(settings.BASE_DIR) / "market_data" / "management" / "commands"
          / "stream_binance_futures.py")


class _FreshStats:
    """STATS is module state shared by one streamer per container. Tests must
    not inherit each other's counts."""

    def setUp(self):
        super().setUp()
        self._saved = dict(fut.STATS)
        for key in fut.STATS:
            fut.STATS[key] = 0

    def tearDown(self):
        fut.STATS.clear()
        fut.STATS.update(self._saved)
        super().tearDown()


class AFailedWriteIsAudibleTests(_FreshStats, TestCase):

    def test_a_successful_funding_write_is_counted(self):
        from django.utils import timezone
        ok = async_to_sync(fut.save_funding)(
            "BTCUSDT", 60000, 60001, 0.0001, None, timezone.now())
        self.assertTrue(ok)
        self.assertEqual(fut.STATS["funding_written"], 1)
        self.assertEqual(fut.STATS["funding_failed"], 0)

        from market_data.models import FundingRate
        self.assertEqual(FundingRate.objects.count(), 1)

    def test_a_failed_funding_write_warns_and_is_counted(self):
        from django.utils import timezone
        with mock.patch("market_data.models.FundingRate.objects.create",
                        side_effect=ValueError("column is too narrow")):
            with self.assertLogs(fut.log, level=logging.WARNING) as caught:
                ok = async_to_sync(fut.save_funding)(
                    "BTCUSDT", 60000, 60001, 0.0001, None, timezone.now())
        self.assertFalse(ok)
        self.assertEqual(fut.STATS["funding_failed"], 1)
        self.assertEqual(fut.STATS["funding_written"], 0)
        joined = "\n".join(caught.output)
        self.assertIn("BTCUSDT", joined)
        self.assertIn("ValueError", joined)
        self.assertIn("column is too narrow", joined)

    def test_a_failed_liquidation_write_warns_and_is_counted(self):
        from django.utils import timezone
        with mock.patch("market_data.models.LiquidationEvent.objects.create",
                        side_effect=ValueError("nope")):
            with self.assertLogs(fut.log, level=logging.WARNING) as caught:
                ok = async_to_sync(fut.save_liquidation)(
                    "ETHUSDT", "LONG", 1, 3000, 3000, timezone.now())
        self.assertFalse(ok)
        self.assertEqual(fut.STATS["liquidations_failed"], 1)
        self.assertIn("ETHUSDT", "\n".join(caught.output))

    def test_a_broken_feed_does_not_flood_but_does_not_hide(self):
        """The first failure is loud, the hundredth is a footnote. Both
        properties matter: a feed broken for an hour must not fill the disk,
        and must not be able to be silent about the first one either."""
        with self.assertLogs(fut.log, level=logging.WARNING) as caught:
            for n in range(1, 251):
                fut._report_failure("save_funding", "BTCUSDT",
                                    ValueError("x"), n)
        self.assertEqual(len(caught.output), 3,
                         f"expected reports at 1, 100 and 200, got "
                         f"{len(caught.output)}: {caught.output}")
        self.assertIn("failure #1", caught.output[0])


class TheHeartbeatSaysWhatLandedTests(_FreshStats, SimpleTestCase):

    def test_the_line_names_written_and_failed_for_both_tables(self):
        fut.STATS.update(funding_written=7, funding_failed=3,
                         liquidations_written=2, liquidations_failed=1,
                         ticks=99, tick_errors=4)
        line = fut.heartbeat_line()
        for fragment in ("99", "7", "3", "2", "1", "4"):
            self.assertIn(fragment, line)
        self.assertIn("written", line)
        self.assertIn("failed", line,
                      "the heartbeat reports only successes; 0 written with "
                      "no failure count is the state that was unreadable")

    def test_it_speaks_when_nothing_has_arrived_at_all(self):
        """The failure this process is worst at showing. A socket that opens
        and delivers nothing used to be indistinguishable from a working
        feed, so the heartbeat runs on its own task rather than inside the
        message loop."""
        async def _drive():
            stop = asyncio.Event()
            task = asyncio.create_task(fut._heartbeat(stop))
            await asyncio.sleep(0.08)
            stop.set()
            await asyncio.wait_for(task, timeout=1)

        with mock.patch.object(fut, "HEARTBEAT_SEC", 0.01):
            with self.assertLogs(fut.log, level=logging.WARNING) as caught:
                asyncio.run(_drive())

        joined = "\n".join(caught.output)
        self.assertIn("NOTHING RECEIVED", joined)

    def test_it_does_not_cry_silence_while_ticks_are_arriving(self):
        # Ten ticks per heartbeat window, so the assertion is about the logic
        # and not about the scheduler: a window that happens to fall between
        # two increments would make a one-tick-per-window test flaky.
        async def _drive():
            stop = asyncio.Event()
            task = asyncio.create_task(fut._heartbeat(stop))
            for _ in range(40):
                fut.STATS["ticks"] += 1
                await asyncio.sleep(0.005)
            stop.set()
            await asyncio.wait_for(task, timeout=1)

        with mock.patch.object(fut, "HEARTBEAT_SEC", 0.05):
            with self.assertLogs(fut.log, level=logging.WARNING) as caught:
                asyncio.run(_drive())

        self.assertNotIn("NOTHING RECEIVED", "\n".join(caught.output))


class TheWriteTasksAreOwnedTests(SimpleTestCase):

    def test_fire_holds_the_task_until_it_finishes(self):
        """`asyncio.create_task` returns a task the loop only weakly holds.
        Dropped, it may be collected before the coroutine runs and its
        exception is never retrieved — the write simply does not happen."""
        async def _drive():
            async def _slow():
                await asyncio.sleep(0.02)
                return "done"

            task = fut._fire(_slow())
            self.assertIn(task, fut._PENDING)
            self.assertEqual(await task, "done")
            await asyncio.sleep(0)
            self.assertNotIn(task, fut._PENDING)

        asyncio.run(_drive())


class TheSourceKeepsItsMouthTests(SimpleTestCase):
    """Read off the source, because the defect was a logging LEVEL and no
    behavioural test can see a level that is configured elsewhere."""

    def setUp(self):
        self.src = SOURCE.read_text(encoding="utf-8")

    def test_no_write_failure_is_reported_at_debug(self):
        for swallowed in ('log.debug("save_funding failed',
                          'log.debug("save_liquidation failed',
                          'log.debug("tick error'):
            self.assertNotIn(
                swallowed, self.src,
                f"{swallowed!r} is back. core.logging_config puts root at "
                f"WARNING when DEBUG is off, so this is not a quiet log line "
                f"— it is no log line at all, and it is how an empty "
                f"FundingRate table survived unexplained.")

    def test_both_write_paths_go_through_the_reporter(self):
        self.assertIn('_report_failure("save_funding"', self.src)
        self.assertIn('_report_failure("save_liquidation"', self.src)

    def test_the_writes_are_fired_through_the_owner(self):
        self.assertIn("_fire(save_funding(", self.src)
        self.assertIn("_fire(save_liquidation(", self.src)
        self.assertNotIn("asyncio.create_task(save_", self.src)

    def test_the_reconnect_line_survives_a_production_log_level(self):
        """Same lesson as the connect line, learned on the same box: an INFO
        line is invisible exactly where it is needed. A worker reconnecting
        in a loop and writing nothing has to be legible from `docker logs`."""
        self.assertNotIn('log.info("reconnect', self.src)
        self.assertIn("futures: reconnect in", self.src)
        reconnect = self.src[self.src.index("futures: reconnect in"):][:200]
        self.assertIn("heartbeat_line()", reconnect,
                      "the reconnect line does not carry the counts, so a "
                      "loop that reconnects cleanly and writes nothing still "
                      "reads as healthy")
