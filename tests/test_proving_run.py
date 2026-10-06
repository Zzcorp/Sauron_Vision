"""THE PROVING RUN (2026-10-05): the history the proving ground needs can
actually be fetched, and the runbook says how.

The proving ground refuses a symbol under 540 days / 800 bars of 4h
history; refresh_bot_bars keeps 200 bars and backfill_bars fetched 600
(100 days), so every verdict read INSUFFICIENT. `backfill_bars --proving`
takes every symbol the judge would walk — the enabled bots', the open
positions', every active instrument of a traded class with 4h bars — at
4h, PROVING_BARS deep, and says the thresholds and the next step. A
hand-typed --intervals or --bars still wins. Nothing trades.

Run with:  python manage.py test tests.test_proving_run
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_backfill_bars_every_class import _cfg, _feed, _instrument


def _run(*args):
    out, err = StringIO(), StringIO()
    call_command("backfill_bars", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def _bar(inst, timeframe="4h"):
    from market_data.models import PriceData
    PriceData.objects.create(
        instrument=inst, timeframe=timeframe,
        timestamp=timezone.now() - timedelta(hours=8),
        open=1, high=1, low=1, close=1, volume=1, source="test")


class TheProvingRunTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("prov_u", password="x")
        _instrument("AAPL", "stock")
        _cfg(self.user, "stock", ["AAPL"])
        self.msft = _instrument("MSFT", "stock")
        self.eur = _instrument("EURUSD", "forex")
        _bar(self.eur)                                   # the universe
        self.zzz = _instrument("ZZZ", "stock")            # no bars: not walked
        self.daily = _instrument("DLY", "etf")
        _bar(self.daily, "1d")                            # daily only: not walked
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg2 = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="held", mode="paper",
            symbols=[], capital=Decimal("500"), enabled=False)
        AssetBotTrade.objects.create(
            config=cfg2, asset_class="stock", symbol="MSFT", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN")

    def test_the_constants(self):
        from market_data.management.commands import backfill_bars as bb
        self.assertEqual((bb.DEFAULT_BARS, bb.PROVING_BARS,
                          bb.PROVING_INTERVALS, bb.DEFAULT_INTERVALS),
                         (600, 4000, "4h", "1h,4h"))
        from backtester.proving.data import MIN_BARS, MIN_SPAN_DAYS
        self.assertEqual((MIN_SPAN_DAYS["4h"], MIN_BARS["4h"]), (540, 800))
        self.assertGreater(bb.PROVING_BARS * 4 / 24, MIN_SPAN_DAYS["4h"],
                           "4000 4h bars span past the floor")

    def test_the_proving_symbols(self):
        from market_data.management.commands.backfill_bars import Command
        self.assertEqual(Command.proving_symbols(), ["AAPL", "EURUSD", "MSFT"])

    def test_proving_walks_every_symbol_at_4h_4000_deep_and_says_the_next_step(self):
        feed = _feed()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed):
            out, err = _run("--proving", "--dry-run")
        self.assertIn("THE PROVING RUN: 3 symbol(s) at 4h, 4000 bars deep "
                      "(dry run)", out)
        calls = {c.args[0]: c.kwargs for c in feed.klines.call_args_list}
        self.assertEqual(set(calls), {"AAPL", "EURUSD", "MSFT"})
        for sym, kw in calls.items():
            self.assertEqual(kw, {"interval": "4h", "limit": 4000}, sym)
        self.assertIn("The proving ground needs 540 days and 800 bars at 4h "
                      "per symbol.", out)
        self.assertIn("prove data", out)
        self.assertIn("component on proving_ground", out)
        self.assertIn("prove rules --save", out)
        self.assertIn("Nothing trades", out)
        from market_data.models import PriceData
        self.assertEqual(PriceData.objects.filter(instrument=self.msft).count(),
                         0, "a dry run writes nothing")

    def test_a_hand_typed_depth_or_interval_wins(self):
        feed = _feed()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed):
            _run("--proving", "--dry-run", "--bars", "300", "--intervals", "1d")
        for c in feed.klines.call_args_list:
            self.assertEqual(c.kwargs, {"interval": "1d", "limit": 300})

    def test_without_proving_the_defaults_are_unchanged(self):
        feed = _feed()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed):
            out, _ = _run("--symbols", "AAPL", "--dry-run")
        self.assertEqual([c.kwargs for c in feed.klines.call_args_list],
                         [{"interval": "1h", "limit": 600},
                          {"interval": "4h", "limit": 600}])
        self.assertNotIn("THE PROVING RUN", out)
        self.assertNotIn("proving ground needs", out)

    def test_proving_with_nothing_to_walk_says_so(self):
        from django.core.management.base import CommandError
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from market_data.models import PriceData
        AssetBotTrade.objects.all().delete()
        AssetBotConfig.objects.all().delete()
        PriceData.objects.all().delete()
        with self.assertRaises(CommandError) as cm:
            _run("--proving", "--dry-run")
        self.assertIn("--proving", str(cm.exception))


class TheRunbookTests(SimpleTestCase):

    def test_the_runbook_has_the_proving_run_in_order(self):
        text = (Path(settings.BASE_DIR) / "deploy" / "RUNBOOK.md").read_text(
            encoding="utf-8")
        self.assertIn("### The proving run", text)
        steps = ["backfill_bars --proving", "prove data",
                 "component on proving_ground", "prove rules --save",
                 "bar_losers"]
        positions = [text.index(s) for s in steps]
        self.assertEqual(positions, sorted(positions), "the five steps in order")
        self.assertIn("540 days / 800 bars", text)
        self.assertIn("nothing trades", text.lower())

    def test_prove_data_prints_the_thresholds(self):
        import inspect
        from backtester.management.commands import prove
        self.assertIn("Needed per symbol", inspect.getsource(prove))
