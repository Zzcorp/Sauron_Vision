"""The harness the evidence was supposed to come from did not run.

Tier 2 of the roadmap is "run a walk-forward over the whole seeded fleet",
because no rule has enough closed trades to be promoted and the allocator
sits at one rule, `tier2`. The harness for that existed — and on its own
defaults it returned nothing at all.

`engine_v2` refuses a dataset shorter than `lookback + 10`. The harness
computed a train window, reported it in every result dict, and then sliced
the TEST RANGE ONLY:

    test_days=30 on 4h bars ->  180 bars, needs 210 -> nothing returned
    test_days=30 on 1d bars ->   30 bars, needs 210 -> nothing returned

An empty window reads as "no trades in this period" rather than "this
harness cannot run", which is the difference between an answer and silence
wearing an answer's clothes.

Run with:  python manage.py test tests.test_walk_forward
"""
from datetime import datetime, timedelta

from django.test import SimpleTestCase

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas ships with the engine
    pd = None


def _frame(days, start=datetime(2025, 1, 1)):
    """A daily OHLCV frame of the shape engine_v2 consumes."""
    idx = pd.DatetimeIndex([start + timedelta(days=i) for i in range(days)])
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
         "volume": 1000.0}, index=idx)


class _Engine:
    """Stands in for BacktestEngineV2, enforcing its one hard floor —
    `len(common_index) < lookback + 10` returns nothing."""

    def __init__(self, seen):
        self.seen = seen

    def run(self, dataframes, lookback=200, trail_pct=0.0):
        self.seen.append({s: len(d) for s, d in dataframes.items()})
        n = min((len(d) for d in dataframes.values()), default=0)
        if n < lookback + 10:
            return {"metrics": None, "trades": []}
        # A trade on every bar past the lookback — which is when a real
        # engine can first signal. Opening one at the MIDPOINT of the fed
        # window would land it in the warm-up, where `_in_range` correctly
        # refuses to count it, and the test would then be measuring the
        # fixture rather than the harness.
        out = []
        for d in dataframes.values():
            for stamp in d.index[lookback:]:
                out.append({"opened_at": stamp.to_pydatetime()})
        return {"metrics": {"bars": n}, "trades": out}


class TheWindowFeedsTheEngineEnoughHistoryTests(SimpleTestCase):

    def setUp(self):
        if pd is None:
            self.skipTest("pandas unavailable")

    def test_a_daily_series_used_to_return_nothing_and_now_does_not(self):
        """Thirty daily bars against a 200-bar lookback. Slicing the test
        range alone gave the engine 30, and it refused every window."""
        from backtester.walk_forward import walk_forward
        seen = []
        out = walk_forward({"EURUSD": _frame(400)}, lambda: _Engine(seen),
                           warmup_days=210, test_days=30, step_days=30,
                           lookback=200)
        self.assertTrue(out, "no windows at all")
        self.assertTrue(any(w["n_trades"] for w in out),
                        "every window still came back empty")

    def test_the_engine_receives_warmup_plus_test_not_test_alone(self):
        from backtester.walk_forward import walk_forward
        seen = []
        walk_forward({"EURUSD": _frame(400)}, lambda: _Engine(seen),
                     warmup_days=210, test_days=30, step_days=30,
                     lookback=200)
        self.assertTrue(seen)
        self.assertGreater(min(v["EURUSD"] for v in seen), 200)

    def test_a_gap_is_distinguishable_from_a_quiet_period(self):
        """An empty window is a result; an unrunnable one is a gap, and the
        old harness rendered both as zero trades."""
        from backtester.walk_forward import walk_forward
        out = walk_forward({"EURUSD": _frame(400)}, lambda: _Engine([]),
                           warmup_days=210, test_days=30, step_days=30,
                           lookback=200)
        self.assertIn("warmup_bars", out[0])
        self.assertIn("n_bars_scored", out[0])
        self.assertGreater(out[0]["warmup_bars"], 0)

    def test_a_series_too_short_to_warm_up_is_named_not_silently_dropped(self):
        from backtester.walk_forward import walk_forward
        out = walk_forward({"EURUSD": _frame(260)}, lambda: _Engine([]),
                           warmup_days=210, test_days=30, step_days=30,
                           lookback=400)
        self.assertTrue(out)
        self.assertIn("skipped", out[0])
        self.assertIn("EURUSD", out[0]["dropped_symbols"])

    def test_no_data_is_an_empty_result_not_a_crash(self):
        from backtester.walk_forward import walk_forward
        self.assertEqual(walk_forward({}, lambda: _Engine([])), [])

    def test_each_window_gets_a_fresh_engine(self):
        """No state — and no fitted parameter — may cross a boundary, which
        is what makes every window out-of-sample by construction."""
        from backtester.walk_forward import walk_forward
        made = []

        def factory():
            e = _Engine([])
            made.append(e)
            return e

        walk_forward({"EURUSD": _frame(400)}, factory, warmup_days=210,
                     test_days=30, step_days=30, lookback=200)
        self.assertGreater(len(made), 1)
        self.assertEqual(len(made), len(set(id(e) for e in made)))


class OnlyTheTestRangeIsScoredTests(SimpleTestCase):
    """A trade the WARM-UP opened is history the window did not choose to
    take, and counting it would report an edge the period never had."""

    def test_a_trade_opened_in_the_warmup_is_not_counted(self):
        from backtester.walk_forward import _in_range
        start, end = datetime(2025, 6, 1), datetime(2025, 7, 1)
        self.assertFalse(_in_range({"opened_at": datetime(2025, 5, 1)},
                                   start, end))
        self.assertTrue(_in_range({"opened_at": datetime(2025, 6, 15)},
                                  start, end))

    def test_it_reads_whichever_field_the_engine_used(self):
        """Engines here have called it opened_at, entry_time and at. A
        harness matching none of them would report a clean zero."""
        from backtester.walk_forward import _in_range
        start, end = datetime(2025, 6, 1), datetime(2025, 7, 1)
        mid = datetime(2025, 6, 15)
        for key in ("opened_at", "entry_time", "at", "time"):
            self.assertTrue(_in_range({key: mid}, start, end), key)

    def test_a_trade_with_no_timestamp_is_counted_not_dropped(self):
        """Dropping it would understate the window rather than admit the
        gap."""
        from backtester.walk_forward import _in_range
        self.assertTrue(_in_range({"pnl": 1.0}, datetime(2025, 6, 1),
                                  datetime(2025, 7, 1)))


class ResultsBeforeTheNewsFixAreVoidTests(SimpleTestCase):
    """`decide()` read the last twelve hours of headlines measured from the
    machine clock, so every historical bar was scored against that day's
    news — lookahead, not noise."""

    def _src(self, *parts):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR).joinpath(*parts)
                ).read_text(encoding="utf-8")

    def test_the_harness_says_the_old_results_are_void(self):
        self.assertIn("Discard them",
                      self._src("backtester", "walk_forward.py"))

    def test_the_engine_passes_the_bar_timestamp(self):
        self.assertIn("as_of=ts", self._src("backtester", "engine_v2.py"))

    def test_the_news_leg_honours_it(self):
        src = self._src("bot_program", "engine", "strategy.py")
        self.assertIn("published_at__lte=end", src)
