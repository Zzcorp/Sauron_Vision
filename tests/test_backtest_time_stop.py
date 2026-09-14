"""The backtest graded a bot that never lets go (2026-09-14).

`bot_program/asset_engine/base.py::_time_stop_hit` flattens a live position
once it has been open longer than `AssetBotConfig.time_stop_setting()`, with
reason TIME. That is the one exit no broker holds: a bracket carries the stop
and the target, and nothing anywhere releases capital from a thesis that
simply never moved.

`bot_program/backtest_asset.py` had never heard of it. It walked up to
`max_bars` bars — 500 by default — and took whatever it found. So the
Scalper persona, which declares an 8-hour ceiling, was backtested as a bot
that holds for three weeks: a target reached on day nine came back as a win
the live bot could not physically have collected, and the run graded a
strategy that does not exist.

Nothing failed. The suite was green, the page rendered, the numbers looked
like numbers. It is the fourth member of the same family found in this
engine in one pass — a measurement that does not measure the thing — and the
only one of the four that made the results BETTER than the truth.

WHAT THIS FILE CONFRONTS

Not a hard-coded hour. The ceiling is read from the model helper the LIVE
engine reads, and the exit the backtester chose is handed to
`time_stop_status()` — the live engine's own read side — which is asked
whether it would consider that trade to have hit its ceiling. The two
sources are the simulator and the thing being simulated. They cannot be
written into agreement with a bug: change the precedence in the model and
both move together; change only the backtester and this breaks.
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

ENGINE = Path(settings.BASE_DIR) / "bot_program" / "backtest_asset.py"

T0 = datetime(2026, 4, 1, 0, 0, tzinfo=dt_tz.utc)

_seq = iter(range(1, 10_000))


def _instrument(symbol="AAPL"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    return inst


def _config(user, **kw):
    from bot_program.models import AssetBotConfig
    fields = dict(
        name=f"TS{next(_seq)}", enabled=True, mode="paper", symbols=["AAPL"],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=2.0, take_profit_pct=4.0,
        entry_score_min=0.6, min_signals_for_entry=1,
        timeframe="1h", cool_down_minutes=0,
    )
    fields.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", **fields)


def _signal(instrument, ts, price=100):
    from signals.models import Signal
    sig = Signal.objects.create(
        instrument=instrument, signal_type="composite", direction="bullish",
        urgency="medium", title="t", description="t", rule_name="r1",
        score=0.85, sub_scores={}, price_at_signal=Decimal(str(price)),
        suggested_entry=Decimal(str(price)))
    Signal.objects.filter(pk=sig.pk).update(created_at=ts)
    return sig


def _bar(instrument, ts, o, h, low, c):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=instrument, timeframe="1h", timestamp=ts,
        open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(low)),
        close=Decimal(str(c)), volume=0, source="test")


class TheCeilingIsHonouredTests(TestCase):

    def setUp(self):
        self.inst = _instrument()
        # Twenty flat hourly bars: neither the stop (98) nor the target (104)
        # is ever touched, so only a time stop can end this trade.
        for hour in range(1, 21):
            _bar(self.inst, T0 + timedelta(hours=hour), 100, 100.5, 99.5, 100)

    def test_a_flat_trade_ends_at_the_ceiling(self):
        from bot_program.backtest_asset import _simulate_exit
        exit_at, price, outcome = _simulate_exit(
            self.inst, "1h", T0, side="BUY", sl=98, tp=104,
            max_bars=500, max_hold_hours=8)
        self.assertEqual(outcome, "time_stop")
        self.assertEqual(exit_at, T0 + timedelta(hours=8))
        self.assertEqual(price, 100)

    def test_no_ceiling_means_no_time_stop(self):
        """`time_stop_setting()` reports hours 0.0 exactly when the stop is
        off, and off has to stay off — a backtest that invented a ceiling
        would be the same defect pointing the other way."""
        from bot_program.backtest_asset import _simulate_exit
        for ceiling in (None, 0, 0.0):
            with self.subTest(ceiling=ceiling):
                _, _, outcome = _simulate_exit(
                    self.inst, "1h", T0, side="BUY", sl=98, tp=104,
                    max_bars=500, max_hold_hours=ceiling)
                self.assertEqual(outcome, "open_at_data_end")

    def test_a_target_reached_after_the_ceiling_is_not_a_win(self):
        """The exact shape of the old overstatement: the price does what you
        hoped, four hours after the bot would have let go."""
        from bot_program.backtest_asset import _simulate_exit
        _bar(self.inst, T0 + timedelta(hours=12, minutes=30),
             100, 108, 99.5, 107)
        _, _, outcome = _simulate_exit(
            self.inst, "1h", T0, side="BUY", sl=98, tp=104,
            max_bars=500, max_hold_hours=8)
        self.assertEqual(outcome, "time_stop")

    def test_a_stop_hit_before_the_ceiling_still_wins_the_race(self):
        """The ceiling must not swallow the exits that come first."""
        from bot_program.backtest_asset import _simulate_exit
        _bar(self.inst, T0 + timedelta(hours=3, minutes=30), 100, 100.5, 97, 98)
        _, price, outcome = _simulate_exit(
            self.inst, "1h", T0, side="BUY", sl=98, tp=104,
            max_bars=500, max_hold_hours=8)
        self.assertEqual(outcome, "stopped_out")
        self.assertEqual(price, 98)


class TheLiveEngineWouldAgreeTests(TestCase):
    """The confrontation. `time_stop_status` is the live read side; it is
    asked about the exit the backtester chose."""

    def setUp(self):
        self.user = User.objects.create_user("ts_live", password="x")
        self.inst = _instrument()
        for hour in range(1, 21):
            _bar(self.inst, T0 + timedelta(hours=hour), 100, 100.5, 99.5, 100)

    def _as_live_trade(self, cfg, opened_at, closed_at):
        from bot_program.models import AssetBotTrade
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL",
            side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
            status="CLOSED", closed_at=closed_at)
        AssetBotTrade.objects.filter(pk=trade.pk).update(opened_at=opened_at)
        trade.refresh_from_db()
        return trade

    def test_the_exit_the_backtest_chose_is_one_the_live_engine_calls_hit(self):
        from bot_program.asset_engine.base import time_stop_status
        from bot_program.backtest_asset import _simulate_exit

        cfg = _config(self.user, max_hold_hours=8.0)
        exit_at, _, outcome = _simulate_exit(
            self.inst, "1h", T0, side="BUY", sl=98, tp=104, max_bars=500,
            max_hold_hours=cfg.effective_max_hold_hours())
        self.assertEqual(outcome, "time_stop")

        status = time_stop_status(
            self._as_live_trade(cfg, T0, exit_at), config=cfg)
        self.assertTrue(
            status["hit"],
            f"the backtest closed at {exit_at} calling it a time stop, and "
            f"the live engine's own reader says the ceiling had not been "
            f"reached: {status}")

    def test_one_bar_earlier_the_live_engine_would_not_have_closed_it(self):
        """Proves the ceiling is not merely somewhere in the vicinity. The
        bar before the exit must NOT be past it, or the backtester is
        closing early and quietly cutting winners."""
        from bot_program.asset_engine.base import time_stop_status
        from bot_program.backtest_asset import _simulate_exit

        cfg = _config(self.user, max_hold_hours=8.0)
        exit_at, _, _ = _simulate_exit(
            self.inst, "1h", T0, side="BUY", sl=98, tp=104, max_bars=500,
            max_hold_hours=cfg.effective_max_hold_hours())
        one_bar_early = exit_at - timedelta(hours=1)
        status = time_stop_status(
            self._as_live_trade(cfg, T0, one_bar_early), config=cfg)
        self.assertFalse(
            status["hit"],
            f"the bar before the backtest's exit was already past the "
            f"ceiling, so the exit is late by at least one bar: {status}")

    def test_the_ceiling_comes_from_the_config_not_from_a_constant(self):
        """Two configs, two ceilings, one set of bars."""
        from bot_program.backtest_asset import _simulate_exit
        for hours in (3.0, 8.0, 15.0):
            with self.subTest(hours=hours):
                cfg = _config(self.user, max_hold_hours=hours)
                exit_at, _, outcome = _simulate_exit(
                    self.inst, "1h", T0, side="BUY", sl=98, tp=104,
                    max_bars=500,
                    max_hold_hours=cfg.effective_max_hold_hours())
                self.assertEqual(outcome, "time_stop")
                self.assertEqual(exit_at, T0 + timedelta(hours=hours))

    def test_a_blank_field_inherits_the_class_ceiling(self):
        """Blank means "track what the platform believes about this class".
        The backtester must inherit that too, or a config nobody has tuned
        is simulated with no ceiling at all."""
        cfg = _config(self.user, max_hold_hours=None)
        self.assertGreater(cfg.effective_max_hold_hours(), 0.0)


class TheRunUsesTheCeilingTests(TestCase):
    """End to end, through `run_backtest`, which is where a wired-up helper
    and an unwired one look identical from the outside."""

    def setUp(self):
        self.user = User.objects.create_user("ts_run", password="x")
        self.inst = _instrument()
        _signal(self.inst, T0 + timedelta(minutes=30))
        for hour in range(1, 21):
            _bar(self.inst, T0 + timedelta(hours=hour), 100, 100.5, 99.5, 100)
        # The target arrives long after any sane ceiling.
        _bar(self.inst, T0 + timedelta(hours=30), 100, 108, 99.5, 107)

    def _run(self, cfg):
        from bot_program.backtest_asset import BacktestParams, run_backtest
        return run_backtest(BacktestParams(
            config_id=cfg.id, start=T0 - timedelta(hours=1),
            end=T0 + timedelta(hours=40)))

    def test_a_tight_ceiling_produces_a_time_stop_not_a_win(self):
        result = self._run(_config(self.user, max_hold_hours=6.0))
        self.assertEqual([t.outcome for t in result.trades], ["time_stop"])
        self.assertEqual(result.stats["by_outcome"]["time_stop"], 1)
        self.assertEqual(result.stats["n_wins"], 0)

    def test_the_same_bars_with_the_ceiling_off_reach_the_target(self):
        """The pair is the point: one input changed, the verdict inverted.
        Before this fix both runs returned the win."""
        result = self._run(_config(self.user, max_hold_hours=0.0))
        self.assertEqual([t.outcome for t in result.trades], ["hit_target"])
        self.assertEqual(result.stats["n_wins"], 1)

    def test_the_time_stop_r_is_a_mark_not_the_target(self):
        result = self._run(_config(self.user, max_hold_hours=6.0))
        trade = result.trades[0]
        self.assertLess(
            trade.realized_r, 1.0,
            "a time-stopped flat trade booked a win's R; the exit price was "
            "taken from the target rather than from the bar")


class TheWiringIsReadOffTheSourceTests(SimpleTestCase):
    """A knob this engine re-derives instead of asking for is a knob that
    drifts. `time_stop_setting()` owns a three-level precedence — legacy
    extras, then the field, then the class default — with a documented reason
    for each level; a backtester reading `cfg.max_hold_hours` directly would
    silently disagree with the live engine on every install that still has
    the legacy key."""

    def setUp(self):
        self.src = ENGINE.read_text(encoding="utf-8")

    def test_the_engine_asks_the_config_for_the_setting(self):
        self.assertIn("cfg.time_stop_setting()", self.src)

    def test_it_does_not_read_the_raw_field(self):
        self.assertNotIn("cfg.max_hold_hours", self.src)
        self.assertNotIn('extras["max_hold_hours"]', self.src)

    def test_the_ceiling_reaches_the_walk(self):
        self.assertIn("max_hold_hours=hold_hours", self.src)

    def test_time_stop_is_one_of_the_outcomes(self):
        from bot_program.backtest_asset import OUTCOMES
        self.assertIn("time_stop", OUTCOMES)
