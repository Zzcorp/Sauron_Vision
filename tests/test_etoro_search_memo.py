"""THE /search MEMO and THE CAUSE OF AN UNPRICED ROW (2026-10-06).

The real NVDA position #131 read "open position only clock-managed: the
broker priced it at 0" at 13:47 UTC, 17 minutes into the US session. The
router builds a fresh EtoroTrader on every call, so the instance's id cache
was cold on every tick and every unpinned symbol cost a /search before its
/rates — and /search answers 429 after a few dozen asks. A refused read was
then recorded with the words of a venue that answered no rate.

  * etoro_client keeps an id eToro answered with an EXACT spelling for the
    UTC day, keyed (world, symbol), across instances (SEARCH_MEMO; off for
    the rest of the suite, whose fake wires count /search calls).
  * the manage tick's skip note names the read's own error when the read
    failed, and keeps "the broker priced it at 0" for a real 0.

Run with:  python manage.py test tests.test_etoro_search_memo
"""
from datetime import date, timedelta
from unittest import mock

from django.test import SimpleTestCase

from bot_program.engine import etoro_client as ec
from tests.test_etoro_client import SEARCH_AAPL, _client


def _searches(fake):
    return [c for c in fake.calls if "/market-data/search" in c[1]]


class _MemoOn:
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(ec, "SEARCH_MEMO", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        ec._SEARCH_IDS.clear()
        self.addCleanup(ec._SEARCH_IDS.clear)


class TheMemoTests(_MemoOn, SimpleTestCase):

    def test_the_suite_runs_with_it_off(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_etoro_client.SEARCH_MEMO = False", src)

    def test_a_second_instance_the_same_day_asks_no_search(self):
        t1, f1 = _client([SEARCH_AAPL], env="live")
        self.assertEqual(t1.instrument_id("AAPL"), 1001)
        self.assertEqual(len(_searches(f1)), 1)
        t2, f2 = _client([SEARCH_AAPL], env="live")
        self.assertEqual(t2.instrument_id("aapl"), 1001)
        self.assertEqual(_searches(f2), [], "the memo answered")
        self.assertEqual(t2._symbols[1001], "AAPL")
        self.assertEqual(t2._venue_spelling[1001], "AAPL")

    def test_the_worlds_are_kept_apart(self):
        t1, _f1 = _client([SEARCH_AAPL], env="live")
        t1.instrument_id("AAPL")
        t2, f2 = _client([SEARCH_AAPL], env="demo")
        t2.instrument_id("AAPL")
        self.assertEqual(len(_searches(f2)), 1)

    def test_a_new_utc_day_asks_again(self):
        t1, _f1 = _client([SEARCH_AAPL], env="live")
        t1.instrument_id("AAPL")
        key = ("live", "AAPL")
        day, iid, spelled = ec._SEARCH_IDS[key]
        ec._SEARCH_IDS[key] = (day - timedelta(days=1), iid, spelled)
        t2, f2 = _client([SEARCH_AAPL], env="live")
        t2.instrument_id("AAPL")
        self.assertEqual(len(_searches(f2)), 1)
        self.assertEqual(ec._SEARCH_IDS[key][0], day)

    def test_a_failure_and_a_lone_misspelled_result_are_never_kept(self):
        refused = ("GET", "/market-data/search", 429, {"message": "slow down"})
        t1, _f1 = _client([refused], env="live")
        with self.assertRaises(Exception):
            t1.instrument_id("AAPL")
        self.assertNotIn(("live", "AAPL"), ec._SEARCH_IDS)
        lone = ("GET", "/market-data/search", 200,
                [{"instrumentId": 97, "internalSymbolFull": "WHEAT.FUT"}])
        t2, _f2 = _client([lone], env="live")
        with self.assertRaises(LookupError):
            t2.instrument_id("WHEAT")
        self.assertNotIn(("live", "WHEAT"), ec._SEARCH_IDS)

    def test_a_pinned_symbol_never_reaches_the_memo(self):
        sym, iid = next(iter(ec.VENUE_ID_PINS.items()))
        t, f = _client([], env="live")
        self.assertEqual(t.instrument_id(sym), iid)
        self.assertEqual(_searches(f), [])
        self.assertEqual(ec._SEARCH_IDS, {})

    def test_off_means_every_instance_asks(self):
        with mock.patch.object(ec, "SEARCH_MEMO", False):
            t1, _f1 = _client([SEARCH_AAPL], env="live")
            t1.instrument_id("AAPL")
            t2, f2 = _client([SEARCH_AAPL], env="live")
            t2.instrument_id("AAPL")
        self.assertEqual(len(_searches(f2)), 1)
        self.assertEqual(ec._SEARCH_IDS, {})


class TheUnpricedNoteNamesTheCauseTests(SimpleTestCase):

    def test_a_failed_read_and_a_real_zero_read_differently(self):
        import inspect
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.manage_positions)
        self.assertIn('mark_err = f"{type(e).__name__}: {e}"[:120]', src)
        self.assertIn('could not be read ({mark_err})', src)
        self.assertIn("broker priced it at 0", src)
        # the failure is kept BEFORE the gate reads it
        self.assertLess(src.index("mark_err = \"\""),
                        src.index("if price is None or price <= 0:"))
