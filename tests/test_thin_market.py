"""A thin market is not a dead feed (2026-10-02).

paper_readiness on the live box: "CBOT_GRAINS is OPEN and 1 symbol(s) have a
4h bar up to 5.7h old — refresh-bot-bars runs every 10 minutes, so the feed
has stopped for them and an armed bot is deciding on a stale candle: OATS".
CBOT oats trade overnight, and thinly: Yahoo writes no hourly bar for an hour
that printed nothing, so the 4h bucket in progress stays empty and the newest
stored bar ages while the writer, asking every ten minutes, gets the same
answer back. The feed had not stopped; the market had not traded.

The writer now records every source answer (market_data.bot_bars:
_note_answer / last_answer) and the bar verdict reads it
(preflight_live._bar_verdict): asked within ANSWER_FRESH_S with nothing newer
than the table is "thin_open", a note; no recent answer, or an answer with
newer bars than the table, is still "late_open", a blocker; and past
THIN_OPEN_MAX_HOURS of open market with no print the source itself is in
doubt again.

Run with:  python manage.py test tests.test_thin_market
"""
import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytz
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from bot_program import campaign_readiness as pr
from bot_program.management.commands.preflight_live import (
    ANSWER_FRESH_S, THIN_OPEN_MAX_HOURS, _bar_verdict, _market_note)

UTC = pytz.UTC
# Thursday 2026-09-17 20:00 CDT: the CBOT grains overnight session is open.
THU_2000_CT = datetime(2026, 9, 18, 1, 0, tzinfo=UTC)


def _row(sym="OATS"):
    return {"instrument__asset_class": "commodity",
            "instrument__exchange": "CBOT", "instrument__symbol": sym}


def _answer(sym, newest, *, asked_s_ago=60, now=THU_2000_CT):
    cache.set(f"bars:answered:{sym}:4h",
              {"at": now.timestamp() - asked_s_ago,
               "newest_ms": int(newest.timestamp() * 1000)}, 3600)


class TheAnswerIsRecordedTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def test_an_answer_records_its_newest_bar(self):
        from market_data.bot_bars import _note_answer, last_answer
        rows = [[1_000, "1", "1", "1", "1", "0"],
                [5_000, "1", "1", "1", "1", "0"],
                [3_000, "1", "1", "1", "1", "0"]]
        _note_answer("OATS", "4h", rows)
        ans = last_answer("OATS", "4h")
        self.assertEqual(ans["newest_ms"], 5_000)
        self.assertLess(time.time() - ans["at"], 5)

    def test_an_empty_answer_is_not_an_answer(self):
        from market_data.bot_bars import _note_answer, last_answer
        _note_answer("OATS", "4h", [])
        _note_answer("OATS", "4h", None)
        self.assertIsNone(last_answer("OATS", "4h"))

    def test_the_writer_notes_the_public_feed_s_answer(self):
        """End to end through refresh_bars_for_config: the keyless feed
        answers, the note is written with the newest bar it had."""
        from market_data import bot_bars
        feed = mock.MagicMock()
        feed._sv_public_feed = True
        feed.klines.return_value = [[7_000, "1", "2", "1", "1.5", "3"]]
        cfg = mock.MagicMock(symbols=["OATS"], asset_class="commodity")
        with mock.patch("instruments.models.Instrument.objects") as objs, \
                mock.patch.object(bot_bars, "_client_for",
                                  return_value=feed), \
                mock.patch.object(bot_bars, "_upsert_rows",
                                  return_value=(1, 0)), \
                mock.patch.object(bot_bars, "_pace"):
            objs.filter.return_value.first.return_value = mock.MagicMock()
            bot_bars.refresh_bars_for_config(cfg, intervals=("4h",))
        self.assertEqual(bot_bars.last_answer("OATS", "4h")["newest_ms"],
                         7_000)


class TheVerdictTests(SimpleTestCase):

    NEWEST = THU_2000_CT - timedelta(hours=5.7)

    def setUp(self):
        cache.clear()

    def test_no_answer_is_still_a_dead_feed(self):
        kind, name, _age = _bar_verdict(_row(), self.NEWEST, THU_2000_CT)
        self.assertEqual((kind, name), ("late_open", "CBOT_GRAINS"))

    def test_a_fresh_answer_with_nothing_newer_is_a_thin_market(self):
        _answer("OATS", self.NEWEST)
        kind, _n, _a = _bar_verdict(_row(), self.NEWEST, THU_2000_CT)
        self.assertEqual(kind, "thin_open")
        note = _market_note(_row(), self.NEWEST, THU_2000_CT)
        self.assertIn("thin market", note)
        self.assertNotIn("OPEN", note)

    def test_a_source_with_newer_bars_is_the_writer_s_fault(self):
        _answer("OATS", self.NEWEST + timedelta(hours=4))
        kind, _n, _a = _bar_verdict(_row(), self.NEWEST, THU_2000_CT)
        self.assertEqual(kind, "late_open")

    def test_an_old_answer_excuses_nothing(self):
        _answer("OATS", self.NEWEST, asked_s_ago=ANSWER_FRESH_S + 60)
        kind, _n, _a = _bar_verdict(_row(), self.NEWEST, THU_2000_CT)
        self.assertEqual(kind, "late_open")

    def test_a_day_without_a_print_is_a_dead_source_again(self):
        newest = THU_2000_CT - timedelta(hours=THIN_OPEN_MAX_HOURS + 1)
        _answer("OATS", newest)
        kind, _n, _a = _bar_verdict(_row(), newest, THU_2000_CT)
        self.assertEqual(kind, "late_open")

    def test_another_symbol_s_answer_excuses_nothing(self):
        _answer("WHEATUSD", self.NEWEST)
        kind, _n, _a = _bar_verdict(_row("OATS"), self.NEWEST, THU_2000_CT)
        self.assertEqual(kind, "late_open")


class TheReadinessReportTests(TestCase):
    """The emitter of the 2026-10-02 line, with its own row query."""

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from market_data.models import PriceData
        cache.clear()
        user = User.objects.create_user("thin_u", password="x")
        AssetBotConfig.objects.create(
            user=user, asset_class="commodity", name="grains", mode="paper",
            symbols=["OATS"], capital=Decimal("10000"), base_currency="EUR",
            enabled=True)
        inst, _ = Instrument.objects.get_or_create(
            symbol="OATS", defaults={"name": "Oats",
                                     "asset_class": "commodity",
                                     "exchange": "CBOT"})
        self.newest = THU_2000_CT - timedelta(hours=5.7)
        PriceData.objects.create(
            instrument=inst, timeframe="4h", timestamp=self.newest,
            open=1, high=2, low=1, close=Decimal("3.5"), volume=10,
            source="yfinance")

    def _report(self):
        with mock.patch("django.utils.timezone.now", return_value=THU_2000_CT):
            return pr.readiness()

    def test_without_an_answer_it_blocks_as_before(self):
        report = self._report()
        self.assertTrue(any("CBOT_GRAINS is OPEN" in b and "OATS" in b
                            for b in report["blockers"]), report["blockers"])

    def test_with_a_fresh_empty_handed_answer_it_is_a_note(self):
        _answer("OATS", self.newest)
        report = self._report()
        self.assertFalse(any("OATS" in b for b in report["blockers"]),
                         report["blockers"])
        self.assertTrue(any("thin market" in n and "OATS" in n
                            for n in report["notes"]), report["notes"])
