"""The backtest button has to actually run a backtest.

`dashboard.views.backtest_create` wrote a BacktestRun row with
status="pending" and returned; the three lines that were meant to hand it
to a worker were commented out and `backtester/tasks.py` did not exist.
Nothing ever picked the row up. The operator saw a history page with no
completed runs and no way to tell a queued run from an abandoned one.

What these tests hold in place is the settle contract: a row handed to
`run_backtest` ends on "completed" with every result field written, or on
"failed" with an error a human can read. It never stays pending. The
one case that is easy to get wrong in the other direction is a run that
produced no trades — that is a RESULT, and marking it failed would throw
away a true answer.

Run with:  python manage.py test tests.test_backtest_runner
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


# ── Fixtures ────────────────────────────────────────────────────────────

def _instrument(symbol="TESTX"):
    from instruments.models import Instrument
    return Instrument.objects.create(
        symbol=symbol, name=f"{symbol} Test Instrument",
        asset_class="stock", is_active=True)


def _bars(instrument, closes, start, timeframe="1d"):
    """Write `closes` as consecutive daily bars starting at `start`.

    High/low straddle the close by 0.5% so the protective-exit path has a
    real range to test against instead of a flat OHLC.
    """
    from market_data.models import PriceData
    rows = []
    for i, close in enumerate(closes):
        ts = timezone.make_aware(datetime.combine(start + timedelta(days=i),
                                                  datetime.min.time()))
        rows.append(PriceData(
            instrument=instrument, timeframe=timeframe, timestamp=ts,
            open=Decimal(str(round(close, 6))),
            high=Decimal(str(round(close * 1.005, 6))),
            low=Decimal(str(round(close * 0.995, 6))),
            close=Decimal(str(round(close, 6))),
            volume=1000, source="test"))
    PriceData.objects.bulk_create(rows)


def _walk(n=400, seed=7, start=100.0):
    """Deterministic pseudo-random walk.

    It has to swing hard enough to push RSI through both thresholds AND
    irregularly enough that the round trips are not all winners — a profit
    factor with no losses to divide by is infinite, which the metrics
    module correctly reports as None, and the happy-path test would then be
    asserting a NULL it caused itself.
    """
    import random
    rng = random.Random(seed)
    price = start
    out = []
    for _ in range(n):
        price *= 1 + rng.uniform(-0.045, 0.045)
        out.append(price)
    return out


def _run(user, **overrides):
    from backtester.models import BacktestRun
    defaults = dict(
        user=user, name="Fixture run", strategy_type="mean_reversion",
        symbols=["TESTX"],
        start_date=date(2024, 4, 1), end_date=date(2024, 12, 1),
        initial_capital=Decimal("10000"),
        # 40/60 rather than 30/70: still RSI mean reversion, but it trades
        # often enough on this fixture to produce both wins and losses.
        parameters={"timeframe": "1d", "oversold": 40, "overbought": 60},
        status="pending")
    defaults.update(overrides)
    return BacktestRun.objects.create(**defaults)


class _RunnerBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("operator", password="pw12345!")
        cls.inst = _instrument()
        # 400 daily bars from 2024-01-01. The window starts in April, so
        # there are 91 bars of real history in front of it — more than the
        # 51 the widest warm-up (SMA 50) asks for.
        _bars(cls.inst, _walk(400), date(2024, 1, 1))

    def setUp(self):
        # maybe_dispatch_async holds a 15-minute in-flight lock in the shared
        # process cache, keyed by run id. SQLite hands out the same row ids
        # after each test's rollback, so without this a later test inherits
        # an earlier one's lock and gets a 409 instead of a dispatch.
        from django.core.cache import cache
        cache.clear()


# ── Happy path ──────────────────────────────────────────────────────────

class HappyPathTests(_RunnerBase):
    def test_every_result_field_is_written(self):
        from backtester.tasks import run_backtest
        run = _run(self.user)
        run_backtest(run.id)
        run.refresh_from_db()

        self.assertEqual(run.status, "completed", run.error)
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(run.error, "")
        # Trades are what make the rest of the fields meaningful; if the
        # fixture stopped producing them this test would silently become a
        # zero-trade test wearing a happy-path name.
        self.assertGreater(run.total_trades, 0)
        for field in ("final_value", "total_return_pct", "max_drawdown_pct",
                      "sharpe_ratio", "win_rate", "avg_win_pct",
                      "profit_factor"):
            self.assertIsNotNone(getattr(run, field), f"{field} left NULL")
        self.assertEqual(run.total_trades,
                         run.winning_trades + run.losing_trades)
        self.assertTrue(run.equity_curve)
        self.assertTrue(run.trades_log)
        self.assertEqual(
            run.final_value,
            Decimal(str(round(float(run.final_value), 2))))

    def test_the_equity_curve_starts_inside_the_requested_window(self):
        """Warm-up bars are fetched from BEFORE the window so the strategy
        can act on day one. They must not leak into the reported curve —
        an equity curve that starts in January for an April backtest is a
        different run than the one the operator asked for."""
        from backtester.tasks import run_backtest
        run = _run(self.user)
        run_backtest(run.id)
        run.refresh_from_db()

        self.assertGreaterEqual(run.equity_curve[0]["date"][:10], "2024-04-01")
        self.assertLessEqual(run.equity_curve[-1]["date"][:10], "2024-12-01")

    def test_no_trade_is_booked_before_the_window_opens(self):
        from backtester.tasks import run_backtest
        run = _run(self.user)
        run_backtest(run.id)
        run.refresh_from_db()
        for t in run.trades_log:
            self.assertGreaterEqual(t["date"][:10], "2024-04-01", t)

    def test_the_run_records_what_the_engine_actually_did(self):
        from backtester.tasks import run_backtest
        run = _run(self.user)
        run_backtest(run.id)
        run.refresh_from_db()
        resolved = run.parameters["_resolved"]
        self.assertEqual(resolved["strategy"], "rsi_mean_reversion")
        self.assertEqual(resolved["timeframe"], "1d")
        self.assertEqual(resolved["warmup_bars_required"], 15)

    def test_each_form_strategy_resolves_to_its_engine_strategy(self):
        from backtester.tasks import resolve_strategy
        for form_value, expected in (("mean_reversion", "rsi_mean_reversion"),
                                     ("trend_follow", "sma_crossover"),
                                     ("momentum", "macd_crossover")):
            key, func, params, warmup = resolve_strategy(form_value, {})
            self.assertEqual(key, expected)
            self.assertTrue(callable(func))
            self.assertGreater(warmup, 0)

    def test_a_trend_follow_run_completes_too(self):
        """SMA needs 51 warm-up bars against RSI's 15 — enough of a
        difference that a warm-up bug would show up on one and not the
        other."""
        from backtester.tasks import run_backtest
        run = _run(self.user, strategy_type="trend_follow")
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.parameters["_resolved"]["warmup_bars_required"], 51)


# ── Protective exits and the closing trade ──────────────────────────────

class EngineExitTests(TestCase):
    """The v1 engine gained two things the runner depends on: static
    stop/target levels, and a force-close that books a TRADE rather than
    only moving the cash."""

    def _frame(self, closes):
        import pandas as pd
        return pd.DataFrame({
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        }, index=pd.date_range("2024-01-01", periods=len(closes), freq="D"))

    def test_a_stop_closes_the_trade_at_the_stop_price(self):
        from backtester.engine import BacktestEngine
        eng = BacktestEngine(initial_capital=10_000, commission_pct=0)
        # Buy on bar 1 at 100, then a 20% drop straight through a 5% stop.
        signals = {1: "buy"}
        eng.run(self._frame([100, 100, 80, 80]),
                lambda df, i: signals.get(i, "hold"), stop_loss_pct=5)
        sells = [t for t in eng.trades if t["action"] == "SELL"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["exit_reason"], "SL")
        self.assertAlmostEqual(sells[0]["price"], 95.0, places=6)

    def test_a_target_closes_the_trade_at_the_target_price(self):
        from backtester.engine import BacktestEngine
        eng = BacktestEngine(initial_capital=10_000, commission_pct=0)
        signals = {1: "buy"}
        eng.run(self._frame([100, 100, 130, 130]),
                lambda df, i: signals.get(i, "hold"),
                stop_loss_pct=5, take_profit_pct=10)
        sells = [t for t in eng.trades if t["action"] == "SELL"]
        self.assertEqual(sells[0]["exit_reason"], "TP")
        self.assertAlmostEqual(sells[0]["price"], 110.0, places=6)

    def test_a_bar_spanning_both_levels_is_taken_as_the_stop(self):
        """A bar reports its high and its low but not their order. Taking
        the target would be assuming the coin landed our way every time."""
        from backtester.engine import BacktestEngine
        eng = BacktestEngine(initial_capital=10_000, commission_pct=0)
        signals = {1: "buy"}
        # Bar 2 closes at 100 but its ±1% range is not enough; widen it by
        # using a close far enough out that both levels sit inside the bar.
        import pandas as pd
        df = pd.DataFrame({
            "open": [100, 100, 100], "high": [101, 101, 120],
            "low": [99, 99, 80], "close": [100, 100, 100],
            "volume": [1000] * 3,
        }, index=pd.date_range("2024-01-01", periods=3, freq="D"))
        eng.run(df, lambda d, i: signals.get(i, "hold"),
                stop_loss_pct=5, take_profit_pct=10)
        sells = [t for t in eng.trades if t["action"] == "SELL"]
        self.assertEqual(sells[0]["exit_reason"], "SL")

    def test_a_position_open_at_the_end_is_booked_as_a_trade(self):
        """The force-close used to move the cash silently, so a run that
        ended holding a position reported a final_value that included the
        sale while total_trades pretended it had never closed."""
        from backtester.engine import BacktestEngine
        eng = BacktestEngine(initial_capital=10_000, commission_pct=0)
        signals = {1: "buy"}
        result = eng.run(self._frame([100, 100, 105, 110]),
                         lambda df, i: signals.get(i, "hold"))
        self.assertEqual(result["total_trades"], 1)
        self.assertEqual(eng.trades[-1]["exit_reason"], "FORCE_CLOSE")
        self.assertEqual(result["winning_trades"], 1)


# ── Failure modes ───────────────────────────────────────────────────────

class FailureTests(_RunnerBase):
    def test_a_symbol_with_no_bars_fails_readably(self):
        from backtester.tasks import run_backtest
        _instrument("EMPTY")
        run = _run(self.user, symbols=["EMPTY"])
        run_backtest(run.id)
        run.refresh_from_db()

        self.assertEqual(run.status, "failed")
        self.assertIn("EMPTY", run.error)
        self.assertIn("no 1d bars stored", run.error.lower())
        self.assertIsNotNone(run.completed_at)

    def test_an_unknown_symbol_names_itself(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, symbols=["NOSUCH"])
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("NOSUCH", run.error)

    def test_a_window_outside_the_stored_history_fails_with_the_span(self):
        """The useful half of "no data" is what data there IS."""
        from backtester.tasks import run_backtest
        run = _run(self.user, start_date=date(2030, 1, 1),
                   end_date=date(2030, 6, 1))
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("2024-01-01", run.error)

    def test_an_unknown_strategy_type_is_rejected(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, strategy_type="wishful_thinking")
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("wishful_thinking", run.error)
        # The error has to carry the way out, not just the complaint.
        self.assertIn("mean_reversion", run.error)

    def test_an_unrunnable_strategy_says_why(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, strategy_type="smc_signals")
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("look-ahead", run.error)

    def test_an_unknown_timeframe_is_rejected(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, parameters={"timeframe": "3s"})
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("3s", run.error)

    def test_an_unexpected_crash_still_settles_the_row(self):
        """The contract is about the row, not about which errors were
        foreseen. Anything that escapes must still leave a failed row with
        a traceable message, never a pending one."""
        from backtester.tasks import run_backtest
        run = _run(self.user)
        with patch("backtester.tasks.execute_run",
                   side_effect=MemoryError("out of room")):
            run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("MemoryError", run.error)
        self.assertIn("out of room", run.error)

    def test_no_symbols_is_rejected(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, symbols=[])
        run_backtest(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("symbol", run.error.lower())

    def test_a_missing_row_does_not_raise(self):
        from backtester.tasks import run_backtest
        result = run_backtest(999_999)
        self.assertEqual(result["status"], "error")


# ── Zero trades is a result ─────────────────────────────────────────────

class ZeroTradeTests(TestCase):
    """A strategy that never triggers has told you something true. Marking
    that run "failed" would throw the answer away, and reporting a 0% win
    rate would invent one."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("quiet", password="pw12345!")
        cls.inst = _instrument("FLATX")
        # A monotone drift has no down closes at all, so RSI pins at 100 and
        # the oversold entry never fires. No trade is ever opened.
        _bars(cls.inst, [100.0 + i * 0.01 for i in range(200)],
              date(2024, 1, 1))

    def test_zero_trades_completes_and_says_so(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, symbols=["FLATX"],
                   start_date=date(2024, 3, 1), end_date=date(2024, 6, 1))
        result = run_backtest(run.id)
        run.refresh_from_db()

        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.total_trades, 0)
        self.assertEqual(run.error, "")
        self.assertIn("no trades", result["note"])

    def test_zero_trades_leaves_trade_statistics_unknown_not_zero(self):
        from backtester.tasks import run_backtest
        run = _run(self.user, symbols=["FLATX"],
                   start_date=date(2024, 3, 1), end_date=date(2024, 6, 1))
        run_backtest(run.id)
        run.refresh_from_db()

        # NULL renders as an em-dash. Zero would read as "it lost every
        # trade it took", which is a claim about trades that never happened.
        self.assertIsNone(run.win_rate)
        self.assertIsNone(run.avg_win_pct)
        self.assertIsNone(run.avg_loss_pct)
        self.assertIsNone(run.profit_factor)
        # Capital was never at risk, so these ARE measured, and they are 0.
        self.assertEqual(float(run.final_value), float(run.initial_capital))
        self.assertEqual(run.total_return_pct, 0)


# ── Dispatch ────────────────────────────────────────────────────────────

class CreateEndpointTests(_RunnerBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.payload = {
            "name": "From the button", "strategy_type": "mean_reversion",
            "symbols": "TESTX", "start_date": "2024-04-01",
            "end_date": "2024-12-01", "initial_capital": "10000",
            "timeframe": "1d", "position_size_pct": "100",
        }

    def test_the_button_enqueues_the_task(self):
        from backtester.models import BacktestRun
        with patch("backtester.tasks.run_backtest.apply_async") as enqueue:
            enqueue.return_value.id = "task-1"
            resp = self.client.post("/backtest/create/", self.payload,
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(resp.json()["ok"])
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["kwargs"],
                         {"run_id": BacktestRun.objects.get().id})

    def test_the_announce_callbacks_ride_along(self):
        """Completion reaches the operator through the run_async link /
        link_error callbacks; without them the worker finishes in silence."""
        with patch("backtester.tasks.run_backtest.apply_async") as enqueue:
            enqueue.return_value.id = "task-1"
            self.client.post("/backtest/create/", self.payload,
                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        kwargs = enqueue.call_args.kwargs
        self.assertIn("link", kwargs)
        self.assertIn("link_error", kwargs)

    def test_a_dead_broker_runs_it_synchronously(self):
        """The failure mode being replaced is a row nobody ever runs. If the
        broker is unreachable the endpoint must execute the run itself, not
        file a second abandoned pending row."""
        from backtester.models import BacktestRun
        with patch("backtester.tasks.run_backtest.apply_async",
                   side_effect=OSError("broker unreachable")):
            resp = self.client.post("/backtest/create/", self.payload,
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        run = BacktestRun.objects.get()
        self.assertEqual(run.status, "completed", run.error)
        self.assertFalse(resp.json()["queued"])

    def test_a_plain_form_post_runs_it_synchronously(self):
        from backtester.models import BacktestRun
        resp = self.client.post("/backtest/create/", self.payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BacktestRun.objects.get().status, "completed")

    def test_two_launches_do_not_lock_each_other_out(self):
        """maybe_dispatch_async holds one in-flight lock per job name. Keyed
        on a constant, the second backtest would 409 for the whole 15-minute
        TTL — so the job name carries the run id."""
        with patch("backtester.tasks.run_backtest.apply_async") as enqueue:
            enqueue.return_value.id = "t"
            first = self.client.post("/backtest/create/", self.payload,
                                     HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            second = self.client.post("/backtest/create/", self.payload,
                                      HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)

    def test_an_unrunnable_strategy_is_refused_without_filing_a_row(self):
        from backtester.models import BacktestRun
        payload = dict(self.payload, strategy_type="breakout")
        resp = self.client.post("/backtest/create/", payload,
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("breakout", resp.json()["error"])
        self.assertEqual(BacktestRun.objects.count(), 0)

    def test_no_symbol_is_refused_without_filing_a_row(self):
        from backtester.models import BacktestRun
        payload = dict(self.payload, symbols="")
        resp = self.client.post("/backtest/create/", payload,
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(BacktestRun.objects.count(), 0)


# ── The page has to tell the four states apart ──────────────────────────

class ListPageTests(_RunnerBase):
    # base.html carries its own data-freshness "STALE" label and its own
    # percentages, so every assertion here targets the pill markup this page
    # emits rather than a bare word that the chrome also contains.
    PILL = {"queued": 'class="bt-pill bt-pill-queue"',
            "running": 'class="bt-pill bt-pill-run"',
            "completed": 'class="bt-pill bt-pill-done"',
            "failed": 'class="bt-pill bt-pill-fail"',
            "stale": 'class="bt-pill bt-pill-stale"'}

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def _html(self):
        resp = self.client.get("/backtest/")
        self.assertEqual(resp.status_code, 200)
        self.last_context = resp.context
        return resp.content.decode()

    def _row(self, html, name):
        """Just the Backtest History row for `name`.

        Scoped twice over: the strip above prints em-dashes of its own, and
        the Top-5 / Worst-5 cards print the same run names, so an unanchored
        search would happily assert against the wrong markup.
        """
        history = html[html.index("Backtest History"):]
        start = history.index(name)
        return history[history.rindex("<tr", 0, start):
                       history.index("</tr>", start)]

    def test_the_empty_state_says_what_to_do(self):
        html = self._html()
        self.assertIn("NO BACKTESTS YET", html)
        self.assertIn("New Backtest", html)

    def test_with_nothing_completed_the_averages_are_em_dashes(self):
        """A 0% average across zero completed runs is a measurement nobody
        made. The page has one honest thing to print, and it is not 0."""
        _run(self.user, status="pending")
        html = self._html()
        for key in ("avg_return", "best_return", "worst_return", "avg_sharpe",
                    "avg_win_rate", "avg_dd"):
            self.assertIsNone(self.last_context[key], key)
        self.assertIn("&mdash;", html)

    def test_a_queued_run_reads_as_queued(self):
        _run(self.user, name="Waiting", status="pending")
        html = self._html()
        self.assertIn(self.PILL["queued"], html)
        self.assertNotIn(self.PILL["completed"], html)

    def test_an_unfinished_row_shows_em_dashes_not_zeroes(self):
        """The whole reason the operator could not read this page: a row
        with no result printed the same 0s a finished losing run would."""
        _run(self.user, name="Waiting", status="pending")
        row = self._row(self._html(), "Waiting")
        self.assertEqual(row.count("&mdash;"), 5)   # return, sharpe, win%, trades, DD
        self.assertNotIn("0.0%", row)
        self.assertNotIn(">0<", row)

    def test_a_completed_zero_trade_row_shows_a_real_zero(self):
        """The mirror image: once a run HAS measured, 0 trades is the
        measurement and must not be hidden behind an em-dash."""
        _run(self.user, name="Measured", status="completed",
             total_return_pct=0.0, total_trades=0, max_drawdown_pct=0.0,
             final_value=Decimal("10000"))
        row = self._row(self._html(), "Measured")
        self.assertIn(">0<", row)

    def test_a_running_run_reads_as_running(self):
        _run(self.user, name="Working", status="running")
        self.assertIn(self.PILL["running"], self._html())

    def test_a_failed_run_shows_its_error(self):
        _run(self.user, name="Broken", status="failed",
             error="No 1d bars for TESTX between 2030-01-01 and 2030-06-01.")
        html = self._html()
        self.assertIn(self.PILL["failed"], html)
        self.assertIn("No 1d bars for TESTX", html)

    def test_a_completed_run_reads_as_completed(self):
        _run(self.user, name="Done", status="completed",
             total_return_pct=12.5, total_trades=8, win_rate=62.5,
             sharpe_ratio=1.2, max_drawdown_pct=4.0,
             final_value=Decimal("11250"))
        html = self._html()
        self.assertIn(self.PILL["completed"], html)
        self.assertIn("12.5%", html)

    def test_a_run_stuck_past_the_lock_ttl_reads_as_stale(self):
        """Anything queued longer than the platform's own in-flight lock TTL
        has no worker behind it. A spinner that never stops is the same lie
        the permanently-pending rows told."""
        from backtester.models import BacktestRun
        from dashboard.run_async import LOCK_TTL_SECONDS
        run = _run(self.user, name="Abandoned", status="pending")
        BacktestRun.objects.filter(pk=run.pk).update(
            created_at=timezone.now() - timedelta(seconds=LOCK_TTL_SECONDS + 60))
        html = self._html()
        self.assertIn(self.PILL["stale"], html)
        self.assertIn("never picked up", html)
        self.assertNotIn(self.PILL["queued"], html)

    def test_a_fresh_queued_run_is_not_called_stale(self):
        _run(self.user, name="Just now", status="pending")
        html = self._html()
        self.assertIn(self.PILL["queued"], html)
        self.assertNotIn(self.PILL["stale"], html)

    def test_a_zero_trade_completed_run_is_labelled_a_result(self):
        _run(self.user, name="Quiet", status="completed",
             total_return_pct=0.0, total_trades=0,
             final_value=Decimal("10000"))
        html = self._html()
        self.assertIn(self.PILL["completed"], html)
        self.assertIn("never triggered", html)


# ── Sibling page: the Phase-18 bot backtester ───────────────────────────

class BotBacktestStripTests(TestCase):
    """Its run button DOES execute — synchronously, inside the request — so
    it never had the pending-forever defect. What it had was a status
    vocabulary mismatch: the model writes "complete"/"error" and the strip
    counted "completed"/"failed", so every aggregate on the page was
    permanently zero however many runs had finished."""

    @classmethod
    def setUpTestData(cls):
        from bot_program.models import BotBacktestRun
        cls.user = User.objects.create_user("botop", password="pw12345!")
        BotBacktestRun.objects.create(
            user=cls.user, config_name_snapshot="Crypto",
            asset_class_snapshot="crypto", status="complete",
            stats={"n_trades": 12, "win_rate": 0.5, "total_r": 3.4})
        BotBacktestRun.objects.create(
            user=cls.user, config_name_snapshot="Forex",
            asset_class_snapshot="forex", status="error",
            error="no bars")

    def test_finished_runs_are_counted(self):
        self.client.force_login(self.user)
        ctx = self.client.get("/bot-backtest/").context
        self.assertEqual(ctx["n_completed"], 1)
        self.assertEqual(ctx["n_failed"], 1)
        self.assertEqual(ctx["avg_trades"], 12.0)
        self.assertIsNotNone(ctx["best_run"])
